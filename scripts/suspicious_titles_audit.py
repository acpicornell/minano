#!/usr/bin/env python3
"""Audit extracted article titles for OCR damage and other anomalies.

Each title that the indexer pulled out of Miñano is checked against
two signals:

1.  **Fuzzy match to NGIB** — every Balearic toponym has a modern
    counterpart in the gazetteer; a title that does not fuzzy-match
    anything in its declared island, even with a permissive threshold,
    is either OCR-garbled or refers to a place that no longer exists
    under that name.

2.  **Pattern heuristics** — recurring OCR confusions seen in this
    corpus:
      * ``BIM`` prefix where Mallorca spelling demands ``BINI``
        (BIMARROY → BINIARROY, BIMBACI → BINIBACI, BUNIALI → BINIALI,
        the NI digraph collapses to M or U).
      * Letter ``K`` in a Romance toponym, almost always a misread
        ``R`` (BINIAKAIG → BINIARAIG, QUIMTAMILLA where N→M).
      * Diaeresis on ``Ü`` outside ``Ü+vowel`` Catalan digraphs —
        the Catalan diaeresis lives in ``üe``/``üi``, never word-final
        or before consonants (BINARAÜS, BIMFAÜALT, BÜÑOLA, SON SÜÑER).
      * Internal mixed-case in an otherwise all-caps headword
        (``Iviza [castillo]`` — typically administrative annotations
        we have inserted manually, but worth surfacing).

A title is flagged if any heuristic triggers OR the best fuzzy match
is under the threshold. Output is grouped by suspicion strength so a
single human pass can resolve them quickly.

Usage:
    python scripts/suspicious_titles_audit.py
    python scripts/suspicious_titles_audit.py --threshold 80
    python scripts/suspicious_titles_audit.py --vol 11
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import duckdb
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_gazetteer import normalize  # noqa: E402

TEXT = ROOT / "data" / "text"
GAZETTEER = ROOT / "data" / "gazetteer.parquet"

# Suffixes that decorate the title but are not part of the toponym.
SUFFIX_RE = re.compile(
    r"\s*\((?:adicio?n[es]?|isla|isla de|Isla|Term|Término|Desp|Jamna|"
    r"estad[ií]sticas?[^)]*|adici[oó]n[^)]*)\)\s*$",
    re.IGNORECASE,
)
BRACKET_RE = re.compile(r"\s*\[[^\]]+\]")
TRAILING_EDITORIAL_RE = re.compile(
    r"\s*[—\-]\s*(?:coordenades|adici[oó]n|isla\s+de).*$",
    re.IGNORECASE,
)


def clean_title(raw: str) -> str:
    t = BRACKET_RE.sub("", raw or "")
    t = TRAILING_EDITORIAL_RE.sub("", t)
    t = SUFFIX_RE.sub("", t)
    return t.strip()


def load_gazetteer():
    con = duckdb.connect(":memory:")
    rows = con.sql(
        f"""SELECT normalized, spelling, island
            FROM read_parquet('{GAZETTEER}')
            WHERE normalized IS NOT NULL AND normalized <> ''"""
    ).fetchall()
    by_island: dict[str, list[tuple[str, str]]] = {}
    all_pool: list[tuple[str, str]] = []
    for norm, spelling, island in rows:
        by_island.setdefault(island, []).append((norm, spelling))
        all_pool.append((norm, spelling))
    return by_island, all_pool


def best_match(norm_t: str, pool: list[tuple[str, str]]):
    if not pool or not norm_t:
        return None, 0
    norms = [p[0] for p in pool]
    hit = process.extractOne(norm_t, norms, scorer=fuzz.WRatio)
    if not hit:
        return None, 0
    matched_norm, score, idx = hit
    return pool[idx][1], score


# Pattern heuristics. Each returns a short explanation when triggered.
def heuristic_flags(title: str) -> list[str]:
    flags = []
    core = clean_title(title)
    upper = core.upper()

    # BIM- where BINI- is expected (Mallorcan toponymy starts with BINI-).
    if re.match(r"^BIM[A-ZÁÉÍÓÚÑÜ]", upper):
        flags.append("BIM- prefix (probably BINI-, NI→M OCR confusion)")
    if re.match(r"^BUM[A-ZÁÉÍÓÚÑÜ]", upper):
        flags.append("BUM- prefix (probably BINI-, NI→U+M)")
    if re.match(r"^BUNI[A-ZÁÉÍÓÚÑÜ]", upper):
        flags.append("BUNI- prefix (probably BINI-, NI→U)")

    # K letter — extremely rare in Catalan/Castilian toponyms.
    if re.search(r"K", upper):
        flags.append("contains K (probably R, OCR R→K)")

    # W letter — even rarer.
    if re.search(r"W", upper):
        flags.append("contains W (unusual for Balearic toponym)")

    # Diaeresis on Ü outside the Catalan «üe»/«üi» digraphs.
    if "Ü" in upper:
        # Allow Ü followed by E or I (canonical Catalan diaeresis).
        if not re.search(r"Ü[EI]", upper):
            flags.append("Ü outside «üe/üi» (OCR umlaut artefact)")

    # Diaeresis on Ï — even rarer in Catalan/Castilian; only valid
    # between vowels (e.g. «raïm», very few toponyms).
    if "Ï" in upper:
        flags.append("Ï present (uncommon in toponyms)")

    # Stray lowercase letters inside a predominantly-uppercase word.
    # Catches OCR confusions like «AÑDRAIG» (stray lowercase n) but
    # leaves Titlecase headwords («Palma», «Iviza») alone.
    for word in core.split():
        if len(word) < 4:
            continue
        uppers = sum(1 for c in word if c.isupper())
        lowers = sum(1 for c in word if c.islower())
        if uppers > 2 * lowers and lowers >= 1:
            flags.append(f"stray lowercase in {word!r} (OCR?)")
            break

    # Stray punctuation often points at OCR noise.
    if re.search(r"[\[\]{}|\\^\"§]", core):
        flags.append("stray punctuation")

    # Consonant clusters that practically never appear in IIBB
    # toponyms (the Mallorcan «tx» / «ny» / «ll» digraphs are fine).
    if re.search(r"KK|WW|QQ|GG[A-Z]|FF[BCDFGHJKLMNPQRSTVWXZ]|VV", upper):
        flags.append("uncommon consonant cluster")

    # Length sanity — single-character or 2-character titles are
    # almost certainly garbage (or admin abbreviations).
    if len(core) <= 2:
        flags.append("title too short")

    return flags


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--threshold",
        type=int,
        default=80,
        help="fuzzy-match floor; titles scoring below are flagged",
    )
    ap.add_argument("--vol", help="restrict to one tomo (e.g. 11)")
    args = ap.parse_args()

    by_island, all_pool = load_gazetteer()

    findings: list[dict] = []
    for path in sorted(TEXT.glob("page_*.json")):
        d = json.loads(path.read_text())
        vol = d["vol"]
        if args.vol and vol != args.vol.zfill(2):
            continue
        leaf = int(d["leaf"])
        for e in d.get("entries", []):
            title = e.get("title", "")
            island = e.get("island")
            flags = heuristic_flags(title)
            core = clean_title(title)
            norm_t = normalize(core)
            pool = by_island.get(island, all_pool) if island else all_pool
            matched, score = best_match(norm_t, pool)
            low_score = score < args.threshold
            # A heuristic flag is reduced to a note when the NGIB
            # match is already strong (>=92): the OCR quirk is real
            # but the geography is correct (e.g. BÜÑOLA matches
            # Buñola at 100 — Miñano's archaic spelling, not
            # ambiguous). Such cases go to the «note» bucket below
            # the suspicious ones.
            strong_match = score >= 92
            if not flags and not low_score:
                continue
            findings.append(
                {
                    "vol": vol,
                    "leaf": leaf,
                    "title": title,
                    "island": island,
                    "matched": matched,
                    "score": score,
                    "flags": flags,
                    "strong_match": strong_match,
                    "file": path.name,
                }
            )

    # Group: probable OCR errors (low score + flags, or low score
    # only, or flags but matched weakly) vs. notes (flag-only with
    # strong match — archaic spelling, not actually broken).
    probable = [f for f in findings if not f["strong_match"]]
    notes = [f for f in findings if f["strong_match"]]

    probable.sort(key=lambda f: (f["score"], f["title"]))
    notes.sort(key=lambda f: f["title"])

    print(
        f"=== {len(probable)} probable issue(s), "
        f"{len(notes)} archaic-spelling note(s) "
        f"(threshold WRatio < {args.threshold}) ===\n"
    )
    if probable:
        print("--- PROBABLE OCR / TITLE PROBLEMS ---\n")
        for f in probable:
            flag_str = "; ".join(f["flags"]) if f["flags"] else "low fuzzy score"
            print(
                f"  [{f['vol']} leaf {f['leaf']:>3}] "
                f"{f['title']!r:42s}  ({f['island'] or '—'})\n"
                f"      flags: {flag_str}\n"
                f"      best NGIB match: {f['matched']!r}  "
                f"(score={f['score']:.0f})\n"
            )
    if notes:
        print("--- ARCHAIC SPELLING (strong NGIB match, OCR-looking but real) ---\n")
        for f in notes:
            flag_str = "; ".join(f["flags"])
            print(
                f"  [{f['vol']} leaf {f['leaf']:>3}] "
                f"{f['title']!r:42s}  →  {f['matched']!r} "
                f"(score={f['score']:.0f})  [{flag_str}]"
            )
    if not findings:
        print("  clean — no suspicious titles found")


if __name__ == "__main__":
    main()
