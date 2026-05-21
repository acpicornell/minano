"""Apply curated OCR-title corrections to the per-tomo JSONL index.

Port of the ``../madoz/scripts/fix_ocr_*_titles.py`` family. Madoz has
one script per OCR-error class (open-paren, close-paren, digit-confusion,
spacing, accent-abbrev, replaced-open-paren); at our current scale
(13 entries in Tomo II) one combined script with grouped FIXES is
enough. Split later if the corpus grows.

Each row in ``FIXES`` carries ``(vol, leaf, old_title, new_title,
comment)``. The ``comment`` documents the source of the correction
— what tells us the original Miñano typography was different from the
OCR output. The script is idempotent: an already-fixed entry is a
no-op.

Policy: we only correct what is clearly an OCR misread, never an
authentic Miñano spelling. The IA facsimile is the source of truth,
not the modern Catalan toponym. If you are unsure whether a variant
is OCR or original, leave the entry alone and re-check against the
facsimile.

  python scripts/fix_ocr_titles.py 02            # dry run
  python scripts/fix_ocr_titles.py 02 --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
INDEX_DIR = PROJECT / "data" / "index"


# ``(vol, leaf, old_title, new_title, comment)``
FIXES: list[tuple[str, int, str, str, str]] = [
    # --- Tomo II ---------------------------------------------------------
    #
    # Spacing — OCR split a single-word toponym at a tall-letter boundary.
    # The Mallorca-castle headword on leaf 63 is printed by Miñano as a
    # single word (the sibling entries ``BELVER DE CINCA`` and ``BELVER
    # DE LOS MONTES`` on the same leaf confirm the printer's house
    # style). The chocr breaks all three at the L–V boundary; we
    # restore the canonical form. Equivalent to madoz's
    # ``fix_ocr_spacing_titles.py``.
    ("02", 63, "BEL VER", "BELVER",
     "OCR split L–V boundary; sibling headwords on leaf 63 print as one word"),
    # Letter confusion — final R misread as U. The CAMPANET article
    # body on leaf 313 mentions ``aneja la de Buger``, confirming the
    # printed form of this Mallorca village's headword is BUGER, not
    # BUGEU. Equivalent to madoz's ``fix_ocr_digit_titles.py`` family
    # (mechanical letter-class confusion, here R↔U).
    ("02", 194, "BUGEU", "BUGER",
     "OCR R→U at word-end; cross-referenced by 'aneja la de Buger' in CAMPANET body"),

    # --- Tomo IX ---------------------------------------------------------
    #
    # OCR h→N: the BSB scan misreads uppercase ``N`` as lowercase ``h``
    # mid-word. The indexer tolerates ``h`` in the title char-class
    # (uppercases it to ``H`` post-match) so the entry is captured, but
    # the canonical spelling needs the literal ``N``. Body says
    # "L. R. de España en la Illa de Mallorca [...] aneja de la de Petra
    # [...] al S. O. de Manacor" — confirms Vilafranca (de Bonany).
    ("09", 331, "VILAFRAHCA", "VILAFRANCA",
     "OCR h→N: BSB scan; Mallorca's Vilafranca de Bonany"),
    # Spacing — OCR split ``VILLACARLOS`` at the L–C boundary. Body
    # places it on Menorca with 870 vec. — that's Villa Carlos
    # (modern Es Castell), the king's-name town built next to Mahón.
    ("09", 362, "VILLAC ARLOS", "VILLACARLOS",
     "OCR L–C boundary split; Menorca's Villa Carlos (now Es Castell)"),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vol", help="Two-digit tomo number (e.g. 02)")
    ap.add_argument("--apply", action="store_true",
                    help="Write the patched JSONL back. Without this, run dry.")
    args = ap.parse_args()

    vol = args.vol.zfill(2)
    in_path = INDEX_DIR / f"tomo{vol}.jsonl"
    if not in_path.exists():
        sys.exit(f"Missing {in_path}. Run scripts/index_volume.py {vol} first.")

    fixes_for_vol = [(leaf, old, new, comment)
                     for v, leaf, old, new, comment in FIXES if v == vol]
    if not fixes_for_vol:
        print(f"No FIXES registered for tomo {vol}.")
        return

    entries = [json.loads(l) for l in in_path.open()]
    plan: list[tuple[dict, str, str, str]] = []
    unmatched: list[tuple[int, str, str]] = []
    for leaf, old, new, comment in fixes_for_vol:
        match = next(
            (e for e in entries
             if e["leaf"] == leaf and e["title"] == old),
            None,
        )
        if match is None:
            # Already applied? Check whether an entry at this leaf
            # carries the NEW title — that means a previous --apply
            # ran. Treat as a no-op rather than an error.
            already = any(e["leaf"] == leaf and e["title"] == new
                          for e in entries)
            if already:
                print(f"  [skip] {vol}/{leaf} {new!r} (already fixed)")
            else:
                unmatched.append((leaf, old, new))
                print(f"  [warn] {vol}/{leaf} {old!r} not found in index "
                      f"(expected to rename → {new!r})")
            continue
        if match["title"] == new:
            print(f"  [skip] {vol}/{leaf} {new!r} (already at target)")
            continue
        plan.append((match, old, new, comment))

    if not plan:
        if unmatched:
            print(f"\n{len(unmatched)} fix(es) unmatched — index drifted or "
                  "tomo not yet indexed at the matching leaves.")
        else:
            print("\nNothing to do.")
        return

    print(f"\n{len(plan)} fixes pending:")
    for entry, old, new, comment in plan:
        print(f"  vol={entry['vol']} leaf={entry['leaf']:>4}  "
              f"{old!r:<22} → {new!r}")
        print(f"      ({comment})")

    if not args.apply:
        print("\nDRY RUN — pass --apply to overwrite the JSONL.")
        return

    for entry, _old, new, _comment in plan:
        entry["title"] = new
    with in_path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"\nApplied {len(plan)} fixes; wrote {len(entries)} entries back "
          f"to {in_path.relative_to(PROJECT)}.")


if __name__ == "__main__":
    main()
