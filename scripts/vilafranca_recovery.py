#!/usr/bin/env python3
"""Article recovery via the fra Lluís de Vilafranca attribution.

Most Balearic adicions in Miñano's Suplemento (Tom XI, 1829) end with
the attribution «Not. dada por el R. P. Fr. Luis de Villafranca», a
fingerprint specific to the Capuchin friar who supplied Miñano with
information on the Balearic Islands. Articles whose title is so
OCR-damaged that the regular indexer cannot recognise them often still
preserve the Vilafranca tail. This script scans every chocr volume,
locates paragraphs whose tail fuzzy-matches the canonical signature,
filters out the many peninsular false positives (the Catalan
«corregimiento de Villafranca» district appears throughout the
dictionary), and reports any paragraph not yet represented in the
extracted corpus under ``data/text/``.

Usage:
    python scripts/vilafranca_recovery.py            # tom XI only (default)
    python scripts/vilafranca_recovery.py --all      # all tomos
    python scripts/vilafranca_recovery.py --vol 05   # specific tomo
    python scripts/vilafranca_recovery.py --threshold 75  # looser fuzzy
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

# Canonical attribution variants — Vilafranca's signature appears in
# several forms across the 11 volumes. The matcher slides each form
# against the paragraph tail using partial_ratio so OCR mangling of
# any single character does not defeat detection.
SIGNATURES = (
    "Not dada por el R P Fr Luis de Villafranca",
    "Noticias dadas por el R P Fr Luis de Villafranca",
    "Noticia dada por el R P Fr Luis de Villafranca",
    "Not dada por el mismo",
    "P Fr Luis de Villafranca",
    "R P Fr Luis de Villafranca",
    "Fr Luis de Villafranca",
)
_SIG_NORM = [
    re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip().lower()
    for s in SIGNATURES
]

# Balearic anchors used to weed out the peninsular Catalan paragraphs
# whose only «Villafranca» reference is the corregimiento name.
BALEARIC_KEYWORDS = (
    "Mallorca", "Menorca", "Iviza", "Ibiza", "Eivissa", "Formentera",
    "Cabrera", "Palma", "Mahon", "Mahón", "Selva", "Inca", "Petra",
    "Pollensa", "Santany", "Santanyí", "Sineu", "Manacor", "Felanitx",
    "Sancellas", "Sencelles", "Alcudia", "Alcúdia", "Lluch", "Lluc",
    "Esporlas", "Esporles", "Bunyola", "Binisalem", "Binissalem",
    "Andraitx", "Andratx", "Valldemos", "Sóller", "Soller", "Llucmayor",
    "Llummayor", "Llucmajor", "Algaida", "Campos", "Caimari", "Caymari",
    "isla y obisp", "en la isla",
)


def signature_score(text: str) -> float:
    """Best fuzzy similarity between any canonical signature and the text."""
    tail = text[-180:]  # the attribution lives in the last lines
    norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", tail)).strip().lower()
    return max(fuzz.partial_ratio(s, norm) for s in _SIG_NORM)


def has_balearic_anchor(text: str) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in BALEARIC_KEYWORDS)


def load_corpus_index() -> tuple[dict, dict, dict]:
    """Returns three indices keyed for fast dedup lookups:
      - by_vol_norm_titles : {vol → {normalised_title, ...}}
      - by_leaf_titles     : {(vol, leaf) → [title, ...]}
      - by_vol_bodies      : {vol → [description_text, ...]}
    Bodies are used for content-level dedup: a Vilafranca-attributed
    paragraph whose title is OCR-mangled (Ariaiii, Üyeró, vecinos…)
    often shares its body's clean prose with an already-extracted
    description. Fuzzy-matching the bodies catches these cases that
    title-level dedup cannot.
    """
    by_vol: dict[str, set[str]] = {}
    by_leaf: dict[tuple[str, int], list[str]] = {}
    by_vol_bodies: dict[str, list[str]] = {}
    for jp in sorted(TEXT.glob("page_*.json")):
        d = json.loads(jp.read_text())
        vol, leaf = d["vol"], int(d["leaf"])
        for e in d.get("entries", []):
            by_vol.setdefault(vol, set()).add(normalize(e["title"]))
            by_leaf.setdefault((vol, leaf), []).append(e["title"])
            desc = e.get("description") or ""
            if desc:
                # Normalise: lowercase, strip punctuation, collapse whitespace
                body = re.sub(r"[^\w\s]", " ", desc).lower()
                body = re.sub(r"\s+", " ", body).strip()
                if len(body) >= 60:
                    by_vol_bodies.setdefault(vol, []).append(body)
    return by_vol, by_leaf, by_vol_bodies


_TITLE_HEAD_RX = re.compile(
    r"\s*([A-ZÁÉÍÓÚÑÜa-zàáéíóú][A-ZÁÉÍÓÚÑÜa-zàáéíóú\d\-]{1,18}"
    r"(?:\s+[A-ZÁÉÍÓÚÑÜa-zàáéíóú\d\-]{1,18}){0,3})"
)


def guess_title(paragraph: str) -> str | None:
    m = _TITLE_HEAD_RX.match(paragraph.strip())
    return m.group(1).strip(" ,.") if m else None


def already_in_corpus(
    title_guess: str, body: str, vol: str, leaf: int,
    by_vol: dict, by_leaf: dict, by_vol_bodies: dict, *,
    leaf_threshold: int = 75, vol_threshold: int = 85,
    body_threshold: int = 70,
) -> bool:
    """True if the corpus already covers this paragraph. Combines two
    signals:

      (a) Title fuzzy-match — fast but unreliable when the candidate
          title is OCR-mangled (Ariaiii ≠ ARIAÑY).
      (b) Body fuzzy-match — compares the clean-Spanish portion of the
          candidate paragraph against the descriptions already in the
          tomo. partial_ratio aligns the shorter description within the
          longer noisy body and produces a high score when both
          describe the same place, even when the title is unreadable.
    """
    norm_g = normalize(title_guess)
    on_leaf = [normalize(t) for t in by_leaf.get((vol, leaf), [])]
    if any(fuzz.WRatio(norm_g, t) >= leaf_threshold for t in on_leaf if t):
        return True
    vol_titles = by_vol.get(vol, set())
    if any(fuzz.WRatio(norm_g, t) >= vol_threshold for t in vol_titles):
        return True
    # Body-level dedup
    body_norm = re.sub(r"[^\w\s]", " ", body).lower()
    body_norm = re.sub(r"\s+", " ", body_norm).strip()
    if len(body_norm) < 60:
        return False
    bodies = by_vol_bodies.get(vol, [])
    return any(
        fuzz.partial_ratio(b, body_norm) >= body_threshold
        for b in bodies
    )


def scan(vol: str, *, threshold: float, max_leaf: int = 700):
    chocr = CHOCR / f"tomo{vol}.html.gz"
    if not chocr.exists():
        return []
    by_vol, by_leaf, by_vol_bodies = load_corpus_index()
    candidates = []
    pars_by_leaf = leaf_paragraphs(chocr, set(range(max_leaf)))
    for leaf, paragraphs in pars_by_leaf.items():
        for para in paragraphs:
            txt = normalize_paragraph(para)
            if not txt or len(txt) < 60:
                continue
            score = signature_score(txt)
            if score < threshold:
                continue
            if not has_balearic_anchor(txt):
                continue
            title = guess_title(txt)
            if not title:
                continue
            if already_in_corpus(title, txt, vol, leaf,
                                 by_vol, by_leaf, by_vol_bodies):
                continue
            candidates.append((vol, leaf, title, score, txt))
    return candidates


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--vol", help="restrict to one tomo (e.g. 11)")
    g.add_argument("--all", action="store_true",
                   help="scan every tomo (default: tom 11 only)")
    ap.add_argument("--threshold", type=float, default=78.0,
                    help="minimum signature similarity (default 78)")
    args = ap.parse_args()

    if args.vol:
        vols = [args.vol.zfill(2)]
    elif args.all:
        vols = sorted(
            re.match(r"tomo(\d+)", p.name).group(1)
            for p in CHOCR.glob("tomo*.html.gz")
        )
    else:
        vols = ["11"]

    total = 0
    for vol in vols:
        print(f"=== Tomo {vol} ===", file=sys.stderr)
        cands = scan(vol, threshold=args.threshold)
        for vol, leaf, title, score, txt in sorted(cands):
            print(f"\n  tom {vol}, leaf {leaf} [sig={score:.0f}]: "
                  f"title guess = {title!r}")
            print(f"    {txt[:380]!r}")
            total += 1
        if not cands:
            print("  (no missing candidates)", file=sys.stderr)
    print(f"\n=== Total candidates: {total} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
