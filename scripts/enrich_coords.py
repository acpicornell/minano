#!/usr/bin/env python3
"""Match each Miñano entry to NGIB coordinates via the gazetteer.

For every entry in data/text/page_*.json we try to find a lat/lon by
fuzzy-matching the title against the Balearic gazetteer (data/gazetteer.parquet).

Match priority:
    1. exact normalized title against a `historical` (curated) variant
    2. exact normalized title against an NGIB entry
    3. fuzzy match (rapidfuzz WRatio ≥ 88) against historical + municipality + capital entries
    4. cross-references: if the entry says "aneja de X" or "contribuye con X",
       we fall back to X's coordinates (so an annex inherits its matrix's location)

Output: writes lat/lon back to a per-leaf coords.json file (we don't touch
the canonical JSONs). export_web_data.py picks this up to inject into the
deployable web/data.json.

Run:
    python3 scripts/enrich_coords.py        # write data/coords.json
    python3 scripts/enrich_coords.py --stats # show match-rate stats
"""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

import duckdb
from rapidfuzz import process, fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from build_gazetteer import normalize  # type: ignore

GAZETTEER = ROOT / 'data' / 'gazetteer.parquet'
OUT = ROOT / 'data' / 'coords.json'


def load_gazetteer():
    """Returns {island: [(normalized, lon, lat, spelling, source, municipality), ...]}"""
    con = duckdb.connect(':memory:')
    rows = con.sql(f"""
        SELECT normalized, lon, lat, spelling, source, municipality, island, local_type
        FROM read_parquet('{GAZETTEER}')
        WHERE lon IS NOT NULL AND lat IS NOT NULL
           OR source = 'historical'
    """).fetchall()
    by_island = {}
    for r in rows:
        norm, lon, lat, spelling, source, mun, isl, ltype = r
        if not norm:
            continue
        by_island.setdefault(isl or '(unknown)', []).append({
            'norm': norm, 'lon': lon, 'lat': lat,
            'spelling': spelling, 'source': source,
            'mun': mun, 'island': isl, 'local_type': ltype,
        })
    return by_island


# Miñano writes "Ibiza" but NGIB uses "Eivissa". Normalise.
ISLAND_ALIAS = {
    'Ibiza': 'Eivissa',
    'Iviza': 'Eivissa',
    'Eivissa': 'Eivissa',
    'Mallorca': 'Mallorca',
    'Menorca': 'Menorca',
    'Formentera': 'Formentera',
    'Cabrera': 'Cabrera',
    'Baleares': None,  # no island centroid — skip
}

# Island centroid fallbacks (rough geographic centers, WGS84)
ISLAND_CENTROID = {
    'Mallorca':   (2.92, 39.60),
    'Menorca':    (4.10, 39.95),
    'Eivissa':    (1.43, 38.97),
    'Formentera': (1.45, 38.69),
    'Cabrera':    (2.93, 39.15),
}


def best_match(title: str, island: str | None, gz_by_island: dict):
    """Find the best (lon, lat) for a Miñano title.

    Strategy:
      1. Look in the entry's island first; fall back to all islands.
      2. Exact normalized match → return its coords.
      3. Fuzzy WRatio match, prefer historical / municipi sources.
      4. If historical variant points to a modern form that itself lacks
         coords, fuzzy-match that modern form against the rest of NGIB.
    """
    norm_title = normalize(title)
    if not norm_title or len(norm_title) < 3:
        return None

    # Translate Miñano's island label to NGIB's
    island_ngib = ISLAND_ALIAS.get(island, island)

    # Candidate pool: prefer same-island, then fall back to all
    pools = []
    if island_ngib and island_ngib in gz_by_island:
        pools.append(gz_by_island[island_ngib])
    all_rows = [r for rows in gz_by_island.values() for r in rows]
    pools.append(all_rows)

    def resolve_to_coords(r, score):
        """r is a gazetteer row; return coords if found, else fuzzy-match its
        municipality (modern Catalan form) against all NGIB rows."""
        if r['lon'] is not None and r['lat'] is not None:
            return {'lon': r['lon'], 'lat': r['lat'],
                    'matched': r['spelling'], 'score': round(score, 1)}
        mun_target = r.get('mun')
        if not mun_target:
            return None
        # Exact spelling match first
        for r2 in all_rows:
            if r2.get('spelling') == mun_target and r2['lon'] is not None:
                return {'lon': r2['lon'], 'lat': r2['lat'],
                        'matched': r2['spelling'], 'score': round(score, 1)}
        # Fuzzy match on the modern municipality
        norm_mun = normalize(mun_target)
        choices2 = [r2['norm'] for r2 in all_rows if r2['lon'] is not None]
        meta2 = [r2 for r2 in all_rows if r2['lon'] is not None]
        if not choices2:
            return None
        result = process.extractOne(norm_mun, choices2, scorer=fuzz.WRatio,
                                    score_cutoff=85)
        if result:
            _, s2, idx2 = result
            r2 = meta2[idx2]
            return {'lon': r2['lon'], 'lat': r2['lat'],
                    'matched': r2['spelling'], 'score': round(min(score, s2), 1),
                    'via_modern': mun_target}
        return None

    for pool in pools:
        # 1. Exact normalized match
        exact = [r for r in pool if r['norm'] == norm_title]
        if exact:
            # Prefer historical (curated) → municipi → first
            exact.sort(key=lambda r: (
                r['source'] != 'historical',
                'Municipi' not in (r.get('local_type') or ''),
            ))
            res = resolve_to_coords(exact[0], 100)
            if res:
                return res

        # 2. Fuzzy match
        choices = [r['norm'] for r in pool]
        meta = pool
        result = process.extractOne(
            norm_title, choices, scorer=fuzz.WRatio, score_cutoff=88,
        )
        if result:
            _, score, idx = result
            res = resolve_to_coords(meta[idx], score)
            if res:
                return res

    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stats', action='store_true',
                    help='print match-rate stats only, do not write')
    args = ap.parse_args()

    print('Loading gazetteer…', file=sys.stderr)
    gz = load_gazetteer()
    total_gz = sum(len(v) for v in gz.values())
    print(f'  {total_gz:,} gazetteer rows across {len(gz)} islands', file=sys.stderr)

    # Output as a list keyed by (vol, leaf, title) so export_web_data can
    # JOIN unambiguously against the DB rows (DB uses an autoincrement id
    # so we can't reuse a positional eid).
    coords = []
    n_total = 0
    n_matched = 0
    n_via_anejo = 0
    missed = []

    for p in sorted((ROOT / 'data' / 'text').glob('page_*.json')):
        d = json.loads(p.read_text())
        for i, e in enumerate(d.get('entries', [])):
            n_total += 1
            island = e.get('island')
            title = e.get('title', '')

            def emit(extra):
                coords.append({
                    'vol': d['vol'], 'leaf': int(d['leaf']),
                    'title': title, **extra,
                })

            match = best_match(title, island, gz)
            if match:
                emit(match)
                n_matched += 1
                continue
            # Fall back to matriz from "contribuye_con" or "municipality"
            mat = (e.get('stats', {}) or {}).get('contribuye_con') or e.get('municipality')
            if mat:
                match = best_match(mat, island, gz)
                if match:
                    match['via_matriz'] = mat
                    emit(match)
                    n_matched += 1
                    n_via_anejo += 1
                    continue
            # Final fallback: island centroid (approximate)
            island_ngib = ISLAND_ALIAS.get(island)
            if island_ngib and island_ngib in ISLAND_CENTROID:
                lon, lat = ISLAND_CENTROID[island_ngib]
                emit({
                    'lon': lon, 'lat': lat,
                    'matched': f'(centroide {island_ngib})',
                    'score': 0,
                    'fallback': 'island-centroid',
                })
                n_matched += 1
                continue
            missed.append((title, island))

    print(f'\n=== match rate ===', file=sys.stderr)
    print(f'  matched directly:    {n_matched - n_via_anejo:>4} / {n_total}', file=sys.stderr)
    print(f'  matched via matriz:  {n_via_anejo:>4}', file=sys.stderr)
    print(f'  TOTAL matched:       {n_matched:>4} / {n_total}  ({n_matched*100/n_total:.1f}%)', file=sys.stderr)
    print(f'  unmatched:           {len(missed):>4}', file=sys.stderr)

    if missed and args.stats:
        print(f'\nFirst 20 unmatched:', file=sys.stderr)
        for title, island in missed[:20]:
            print(f'    {title!r:40s} [{island}]', file=sys.stderr)

    if not args.stats:
        OUT.write_text(json.dumps(coords, indent=2))
        print(f'\nWrote {len(coords)} coord pairs → {OUT.relative_to(ROOT)}', file=sys.stderr)

if __name__ == '__main__':
    main()
