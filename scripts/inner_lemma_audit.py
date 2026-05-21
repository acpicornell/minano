#!/usr/bin/env python3
"""Audit chOCR paragraphs for Balearic lemmas buried mid-paragraph.

The main indexer (``scripts/index_volume.py``) matches Miñano lemmas
anchored to the start of a chOCR paragraph: it expects each article
to begin its own paragraph block. The chOCR sometimes fails to break
between consecutive articles, however, and a Balearic entry can end
up sharing a paragraph with the tail of the preceding (often
peninsular) one. In that situation the indexer is blind to the
buried article — the SINEU article (Tom VIII, leaf 308, merged with
the tail of SINES of Portugal) and RUBERTS (Tom VII, leaf 375,
merged with the tail of QUINTANAPALLA) were both missed for exactly
this reason.

This script scans every chOCR paragraph for the Miñano lemma
signature «TITLE, V.|L.|C.|Ald. …» occurring **after** the first
30 characters of a paragraph and followed within 250 characters by
an explicit Balearic anchor (Mallorca, Menorca, Ibiza, Eivissa,
Formentera, Cabrera, Baleares, Palma, Mahon, plus the more generic
«isla y obisp» / «en la isla» phrasing). Candidates whose title is
already represented in ``data/text/`` (fuzzy WRatio ≥ 80) are
dropped. The remaining list is small — across all eleven volumes
the audit reports under five candidates, of which most are
peninsular false positives where the Balearic anchor matches a
homonymous place name (the León-province district of Cabrera, for
instance).

Run periodically — for example after a fresh extraction pass — to
verify that no Balearic article has been silently merged into a
neighbouring entry.

Usage:
    python scripts/inner_lemma_audit.py                # all tomos
    python scripts/inner_lemma_audit.py --vol 08       # one tomo
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_gazetteer import normalize  # noqa: E402
from extract_text import leaf_paragraphs, normalize_paragraph  # noqa: E402

CHOCR = ROOT / "data" / "chocr"
TEXT = ROOT / "data" / "text"

INNER_LEMMA = re.compile(
    r"(?<![A-ZÁÉÍÓÚÑÜa-záéíóúñü0-9])"
    r"([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\d\-\']{2,18}"
    r"(?:\s+[A-ZÁÉÍÓÚÑÜ\d\-\.,()]{1,15}){0,3})"
    r"\s*,\s*"
    r"(V|L|C|Ald|Aid|Cas|Cot|Desp|Felig|Parr|Jurisd|R|S)\.?"
)

BALEARIC_ANCHOR = re.compile(
    r"(?:Mallorca|Menorca|Iv[iy]za|Ibiza|Eivissa|Formentera|Cabrera|Baleares|"
    r"Palma|Mahon|Mahón|isla y obisp|en la isla)",
    re.IGNORECASE,
)


def load_existing_titles() -> dict[str, set[str]]:
    by_vol: dict[str, set[str]] = {}
    for jp in sorted(TEXT.glob("page_*.json")):
        d = json.loads(jp.read_text())
        for e in d.get("entries", []):
            by_vol.setdefault(d["vol"], set()).add(normalize(e["title"]))
    return by_vol


def scan(vol: str, by_vol: dict[str, set[str]]):
    chocr = CHOCR / f"tomo{vol}.html.gz"
    if not chocr.exists():
        return []
    candidates = []
    pars_by_leaf = leaf_paragraphs(chocr, set(range(700)))
    for leaf, paras in pars_by_leaf.items():
        for para in paras:
            txt = normalize_paragraph(para)
            if not txt or len(txt) < 60:
                continue
            for m in INNER_LEMMA.finditer(txt):
                if m.start() < 30:
                    continue
                title_raw = m.group(1).strip()
                # require a pure-caps first word — avoids matching
                # mixed-case sentence starts like «Don Juan, V. de …»
                first_word = title_raw.split()[0]
                if not re.match(r"^[A-ZÁÉÍÓÚÑÜ]{3,}$", first_word):
                    continue
                tail = txt[m.end():m.end() + 250]
                if not BALEARIC_ANCHOR.search(tail):
                    continue
                norm_t = normalize(title_raw)
                if any(
                    fuzz.WRatio(norm_t, t) >= 80
                    for t in by_vol.get(vol, set())
                ):
                    continue
                ctx = txt[max(0, m.start() - 50):m.start() + 250]
                candidates.append((leaf, title_raw, ctx))
    return candidates


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vol", help="restrict to one tomo (e.g. 08)")
    args = ap.parse_args()

    if args.vol:
        vols = [args.vol.zfill(2)]
    else:
        vols = sorted(
            re.match(r"tomo(\d+)", p.name).group(1)
            for p in CHOCR.glob("tomo*.html.gz")
        )

    by_vol = load_existing_titles()
    total = 0
    for vol in vols:
        cands = scan(vol, by_vol)
        if not cands:
            print(f"=== Tom {vol}: clean ===", file=sys.stderr)
            continue
        print(f"\n=== Tom {vol}: {len(cands)} candidate(s) ===")
        for leaf, title, ctx in cands:
            print(f"\n  leaf {leaf}: {title!r}")
            print(f"    {ctx!r}")
            total += 1
    print(f"\n=== Total: {total} candidate(s) across {len(vols)} tomo(s) ===",
          file=sys.stderr)


if __name__ == "__main__":
    main()
