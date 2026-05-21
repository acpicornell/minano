"""Probe the chOCR paragraph structure of a Miñano tomo.

Goal: confirm whether one chocr paragraph ≈ one Miñano entry (as is the
case for Madoz), or whether paragraphs glue multiple entries together.

Prints sample paragraphs from leaves in the middle of the volume,
plus paragraphs that contain Balearic mentions. Used once during
pipeline calibration; safe to delete afterwards.

Run: python scripts/probe_paragraphs.py <vol>
"""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CHOCR_DIR = PROJECT / "data" / "chocr"

PAGE_PAT = re.compile(r'class="ocr_page" id="page_(\d+)"')
PAR_OPEN_PAT = re.compile(r'<p class="ocr_par"')
CHAR_PAT = re.compile(r'<span class="ocrx_cinfo"[^>]*>([^<])</span>')

BAL_PAT = re.compile(
    r'\b(?:Mallorca|Menorca|Ibiza|Iviza|Formentera|Cabrera|Baleares)\b',
    re.IGNORECASE,
)


def iter_paragraphs(chocr_path: Path):
    opener = gzip.open if chocr_path.suffix == ".gz" else open
    current_leaf = None
    buf: list[str] = []
    in_par = False
    with opener(chocr_path, "rt", encoding="utf-8") as f:
        for line in f:
            m_page = PAGE_PAT.search(line)
            if m_page:
                if buf:
                    yield current_leaf, "".join(buf)
                    buf = []
                current_leaf = int(m_page.group(1))
                in_par = False
                continue
            if PAR_OPEN_PAT.search(line):
                if buf:
                    yield current_leaf, "".join(buf)
                    buf = []
                in_par = True
                continue
            if "</p>" in line:
                if buf:
                    yield current_leaf, "".join(buf)
                    buf = []
                in_par = False
                continue
            if in_par:
                for cm in CHAR_PAT.finditer(line):
                    buf.append(cm.group(1))
    if buf:
        yield current_leaf, "".join(buf)


def main() -> None:
    vol = sys.argv[1].zfill(2) if len(sys.argv) > 1 else "02"
    chocr_path = CHOCR_DIR / f"tomo{vol}.html.gz"
    paragraphs = list(iter_paragraphs(chocr_path))
    print(f"Total paragraphs: {len(paragraphs)}")
    lengths = [len(p[1]) for p in paragraphs if p[1]]
    if lengths:
        lengths.sort()
        n = len(lengths)
        print(f"Lengths — min: {lengths[0]}, "
              f"p50: {lengths[n//2]}, p90: {lengths[int(n*0.9)]}, "
              f"max: {lengths[-1]}")

    # Sample paragraphs around the middle (avoiding front matter).
    print("\n=== 5 sample paragraphs from leaf 200 ===")
    sampled = 0
    for leaf, par in paragraphs:
        if leaf == 200 and par.strip():
            norm = re.sub(r"\s+", " ", par).strip()
            print(f"\n[leaf {leaf}] ({len(norm)} chars)")
            print(norm[:500])
            sampled += 1
            if sampled >= 5:
                break

    # Sample paragraphs that mention Balearic places.
    print("\n=== 5 paragraphs mentioning Balearic places ===")
    sampled = 0
    for leaf, par in paragraphs:
        if not par.strip():
            continue
        norm = re.sub(r"\s+", " ", par).strip()
        if BAL_PAT.search(norm):
            print(f"\n[leaf {leaf}] ({len(norm)} chars)")
            print(norm[:600])
            sampled += 1
            if sampled >= 5:
                break


if __name__ == "__main__":
    main()
