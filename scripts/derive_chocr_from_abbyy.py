"""Derive chOCR + page_numbers from an Internet Archive ABBYY raw dump.

For Miñano's Tomos V and X, Internet Archive's chocr.html.gz file is
not generated (only djvu.txt, djvu.xml, _abbyy.gz, and PDF are
served). Since IA derives the chocr from the ABBYY FineReader XML
itself, we can do the same locally — using IA's own open-source
toolchain.

This script:
  1. Downloads ``<identifier>_abbyy.gz`` from Internet Archive.
  2. Runs ``abbyy-to-hocr`` (from the ``archive-hocr-tools`` package)
     to convert ABBYY FineReader v6 XML → hOCR HTML.
  3. Gzip-compresses the result to ``data/chocr/tomo<vol>.html.gz``,
     producing a file structurally identical to IA-served chocr —
     the same parsers (``iter_paragraphs``) consume it unchanged.
  4. Runs ``hocr-pagenumbers`` to derive a leaf→printed-page map,
     written to ``data/page_numbers/tomo<vol>.json``.
  5. Downloads the convenience ``_djvu.txt`` for ad-hoc grep parity.

Dependencies (one-time, ``pip install …``):

    archive-hocr-tools  scikit-learn  viterbi-trellis  roman

Run: ``python scripts/derive_chocr_from_abbyy.py <vol>``  (e.g. ``05``)
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"
UA = "Mozilla/5.0 (research)"

# Tomos that IA serves only as ABBYY raw (no chocr.html.gz). Keep the
# canonical mapping here, mirroring fetch_volume.py's VOL_TO_IDENTIFIER
# so this script is self-contained.
ABBYY_DERIVED: dict[str, str] = {
    # Tomo V — HIT-MEMBRIVE. Contains the critical MALLORCA / MAHON /
    # MENORCA / MANACOR / INCA / MARÍA / LLOSETA / LLUBÍ / LLUCALCARI
    # / LLORITO entries. Google scan via Complutense.
    "05": "diccionariogeog06machgoog",
    # Tomo X — post-VIL. The IA scan is partial (~125 pages of body,
    # then back-matter), so coverage is limited and Balearic content
    # is effectively zero. Kept here for reproducibility.
    "10": "diccionariogeog02bedogoog",
}


def _download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.relative_to(PROJECT)} already exists "
              f"({dest.stat().st_size/1024/1024:.1f} MB)")
        return
    print(f"  [GET]  {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as r:
        dest.write_bytes(r.read())
    print(f"  [OK]   {dest.relative_to(PROJECT)} "
          f"({dest.stat().st_size/1024/1024:.1f} MB)")


def derive(vol: str) -> None:
    identifier = ABBYY_DERIVED[vol]
    print(f"=== Tomo {vol} ({identifier}) — ABBYY-derived ===")

    # Output paths
    out_chocr = DATA / "chocr" / f"tomo{vol}.html.gz"
    out_pn = DATA / "page_numbers" / f"tomo{vol}.json"
    out_djvu = DATA / "txt_djvu" / f"tomo{vol}.txt"

    if out_chocr.exists() and out_pn.exists() and out_djvu.exists():
        print(f"  [skip] all outputs already present for tomo {vol}")
        return

    # Work in a temp dir so the 100+ MB intermediate ABBYY XML is
    # auto-cleaned up.
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        abbyy_gz = td_path / f"{identifier}_abbyy.gz"
        abbyy_xml = td_path / f"{identifier}_abbyy"
        hocr_html = td_path / f"{identifier}_hocr.html"

        _download(
            f"https://archive.org/download/{identifier}/{identifier}_abbyy.gz",
            abbyy_gz,
        )

        print("  [GUNZIP]")
        with gzip.open(abbyy_gz, "rb") as zin, abbyy_xml.open("wb") as zout:
            shutil.copyfileobj(zin, zout)
        print(f"  [OK]   ABBYY XML: {abbyy_xml.stat().st_size/1024/1024:.0f} MB")

        print("  [abbyy-to-hocr]")
        with hocr_html.open("wb") as fp_out:
            subprocess.run(
                ["abbyy-to-hocr", "-f", str(abbyy_xml)],
                check=True, stdout=fp_out,
            )
        print(f"  [OK]   hOCR HTML: {hocr_html.stat().st_size/1024/1024:.0f} MB")

        print("  [gzip → tomo{vol}.html.gz]".format(vol=vol))
        out_chocr.parent.mkdir(parents=True, exist_ok=True)
        with hocr_html.open("rb") as fin, gzip.open(out_chocr, "wb", compresslevel=9) as fout:
            shutil.copyfileobj(fin, fout)
        print(f"  [OK]   {out_chocr.relative_to(PROJECT)} "
              f"({out_chocr.stat().st_size/1024/1024:.1f} MB)")

        print("  [hocr-pagenumbers]")
        out_pn.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["hocr-pagenumbers",
             "-f", str(out_chocr),
             "-o", str(out_pn),
             "-I", identifier],
            check=True,
        )
        print(f"  [OK]   {out_pn.relative_to(PROJECT)} "
              f"({out_pn.stat().st_size/1024:.0f} KB)")

    # Convenience djvu.txt download (separate, IA serves it directly).
    _download(
        f"https://archive.org/download/{identifier}/{identifier}_djvu.txt",
        out_djvu,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vol", help="Two-digit tomo number (e.g. 05)")
    args = ap.parse_args()
    vol = args.vol.zfill(2)
    if vol not in ABBYY_DERIVED:
        sys.exit(f"Tomo {vol} not registered for ABBYY derivation. "
                 f"Known: {sorted(ABBYY_DERIVED)}.")
    derive(vol)


if __name__ == "__main__":
    main()
