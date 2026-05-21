"""Dump the chocr plaintext for a list of (vol, leaf) targets.

Used to feed Claude (in-conversation, "Max path") the same chocr
input that ``extract_text.py`` would send to the Sonnet API. For each
target writes:

    data/text/_chocr/page_<vol>_<leaf>.txt

The .txt has two sections: TARGET LEAF and CONTINUATION LEAF +N
(continuation context).

For Miñano this reads source-of-truth from the per-tomo JSONL index
(``data/index/tomo<vol>.jsonl``) rather than DuckDB — at the chocr
staging step the DB isn't built yet.

Run:
  python scripts/stage_chocr.py 02:137 09:331 09:362
  python scripts/stage_chocr.py --from-index --vol 09
  python scripts/stage_chocr.py --from-index            # ALL balearic leaves
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
INDEX_DIR = PROJECT / "data" / "index"
CHOCR_DIR = PROJECT / "data" / "chocr"
OUT_DIR = PROJECT / "data" / "text" / "_chocr"

sys.path.insert(0, str(PROJECT / "scripts"))
from extract_text import build_leaf_text, pick_window  # type: ignore


def _load_index_for(vol: str) -> list[dict]:
    p = INDEX_DIR / f"tomo{vol}.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.open()]


def stage(vol: str, leaf: int, window: int | None = None) -> Path:
    chocr_path = CHOCR_DIR / f"tomo{vol}.html.gz"
    if not chocr_path.exists():
        raise FileNotFoundError(chocr_path)

    index = _load_index_for(vol)
    titles = [e for e in index if e["leaf"] == leaf]
    pp = titles[0].get("page_printed") if titles else None
    if window is None:
        window = pick_window(titles) if titles else 2
    leaf_text, continuations = build_leaf_text(chocr_path, leaf, window=window)

    header = (
        f"# tom{vol} leaf {leaf}  printed page {pp or '?'}  window={window}\n"
        f"# chocr-indexed Balearic entries on this leaf ({len(titles)}):\n"
    )
    for t in titles:
        header += f"#   - {t['title']}\n"

    body = "=== TARGET LEAF ===\n" + leaf_text
    for i, cont in enumerate(continuations, start=1):
        body += f"\n\n=== CONTINUATION LEAF +{i} ===\n{cont}"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"page_{vol}_{leaf}.txt"
    out.write_text(header + "\n" + body)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("targets", nargs="*",
                    help="VOL:LEAF pairs (e.g. 02:137 09:331)")
    ap.add_argument("--from-index", action="store_true",
                    help="auto-stage every Balearic leaf in the per-tomo index JSONLs")
    ap.add_argument("--vol", default=None,
                    help="--from-index: restrict to one tomo (e.g. 09)")
    ap.add_argument("--skip-done", action="store_true",
                    help="--from-index: skip leaves that already have data/text/page_<vol>_<leaf>.json")
    ap.add_argument("--window", type=int, default=None,
                    help="force window size (default: auto — 4 for mega-entries, 2 otherwise)")
    args = ap.parse_args()

    if args.from_index:
        pairs: list[tuple[str, int]] = []
        files = sorted(INDEX_DIR.glob("tomo*.jsonl"))
        if args.vol:
            files = [f for f in files if f.stem == f"tomo{args.vol.zfill(2)}"]
        seen: set[tuple[str, int]] = set()
        for f in files:
            for line in f.open():
                e = json.loads(line)
                key = (e["vol"], int(e["leaf"]))
                if key in seen:
                    continue
                seen.add(key)
                if args.skip_done:
                    done = (PROJECT / "data" / "text" /
                            f"page_{key[0]}_{key[1]}.json")
                    if done.exists():
                        continue
                pairs.append(key)
    else:
        pairs = []
        for t in args.targets:
            vol, leaf = t.split(":")
            pairs.append((vol.zfill(2), int(leaf)))

    if not pairs:
        sys.exit("No targets to stage.")

    for vol, leaf in pairs:
        try:
            out = stage(vol, leaf, window=args.window)
            size = out.stat().st_size
            print(f"  [ok] {out.relative_to(PROJECT)}  ({size:,} bytes)")
        except Exception as e:
            print(f"  [fail] tom{vol} leaf{leaf}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
