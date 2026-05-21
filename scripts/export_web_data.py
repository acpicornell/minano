"""Export text_entries to a single web/data.json — consumed directly
by the static web (no DuckDB-WASM, no server).

Format mirrors ``../madoz/scripts/export_web_data.py``, with the
Miñano-specific schema diffs:

- ``seigneurial_regime`` and ``mayor_type`` replace madoz's
  ``judicial_district`` (Miñano predates the partido-judicial reform).
- No ``madoz_url`` / ``madoz_content`` — there is no third-party
  WordPress mirror to cross-reference.
- ``ia_url`` is built from the per-tomo IA identifier (heterogeneous
  for Miñano, unlike madoz's regular pattern).

Run after any data refresh:

  python scripts/export_web_data.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import duckdb

PROJECT = Path(__file__).resolve().parent.parent
DB = PROJECT / "db" / "minano.duckdb"
OUT = PROJECT / "web" / "data.json"


def _load_vol_to_identifier() -> dict[str, str]:
    """Pull the canonical vol→IA-identifier map from fetch_volume.py."""
    spec = importlib.util.spec_from_file_location(
        "_fetch_volume", PROJECT / "scripts" / "fetch_volume.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.VOL_TO_IDENTIFIER


def main() -> None:
    if not DB.exists():
        sys.exit(f"DB not found at {DB}. Run scripts/load_text.py first.")
    vol_to_id = _load_vol_to_identifier()

    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        """
        SELECT id, vol, leaf, page_printed, title,
               place_type, island, seigneurial_regime, mayor_type,
               municipality, description, stats, cross_references,
               confidence
        FROM text_entries
        ORDER BY title
        """
    ).fetchall()
    cols = [
        "id", "vol", "leaf", "page_printed", "title",
        "place_type", "island", "seigneurial_regime", "mayor_type",
        "municipality", "description", "stats", "cross_references",
        "confidence",
    ]

    entries = []
    for row in rows:
        d = dict(zip(cols, row))
        # ``stats`` arrives as a JSON string from DuckDB; parse so the
        # frontend doesn't have to re-parse a string per row.
        if isinstance(d["stats"], str) and d["stats"]:
            try:
                d["stats"] = json.loads(d["stats"])
            except json.JSONDecodeError:
                d["stats"] = None
        if d["cross_references"] is None:
            d["cross_references"] = []
        # Facsimile link to the Internet Archive scan. Page-level (one
        # leaf can hold several entries); the UI surfaces that.
        identifier = vol_to_id.get(d["vol"])
        if identifier:
            d["ia_url"] = (
                f"https://archive.org/details/{identifier}"
                f"/page/n{d['leaf']}/mode/2up"
            )
        # Drop empty/falsy fields to keep the JSON compact.
        for k in list(d):
            if d[k] in (None, "", []):
                del d[k]
        entries.append(d)

    payload = {
        "generated_with": "scripts/export_web_data.py",
        "text_total": len(entries),
        "entries": entries,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Wrote {OUT.relative_to(PROJECT)}  "
          f"({OUT.stat().st_size/1024:.1f} KB, {len(entries)} entries)")


if __name__ == "__main__":
    main()
