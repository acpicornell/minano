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

# Curated coordinates for titles whose toponym appears in NGIB under
# multiple homonyms and where the content of the Miñano article makes
# the intended referent unambiguous even though the string match cannot.
# Key is the (island, normalised-title) tuple after `_strip_editorial`
# and `normalize`. Value is (lon, lat, human-readable spelling).
CURATED_OVERRIDES = {
    ('Mallorca', 'VILETA'):    (2.6207, 39.5929, 'la Vileta (Palma)'),
    ('Mallorca', 'RULLO'):     (2.6213, 39.6269, 'Establiments (Palma)'),
    # Son Lluc apareix en més d'un municipi mallorquí; l'article el situa
    # «al NO i a ⅔ de llegua de Palma, al S i a una milla curta de la
    # Vileta». Coordenades en aquest entorn.
    ('Mallorca', 'SON LLUCH'): (2.7503, 39.5899, 'Son Lluc (Palma)'),
    # Salinas (las): l'article descriu el nucli annex de Santanyí amb 290
    # habitants i salines. És inequívocament el municipi modern ses Salines.
    ('Mallorca', 'SALINAS LAS'): (3.0535, 39.3392, 'ses Salines'),
    # Mirabona: aldea-annex de Selva «al N. de Caymari», als monts que
    # envolten Lluc. No hi ha topònim NGIB amb aquest nom; assignem
    # coordenades aproximades a la zona de muntanya al nord de Caimari,
    # sobre el camí de Lluc.
    ('Mallorca', 'MIRABONA'):  (2.9000, 39.7900, 'Mirabona (entorn de Lluc)'),
}

# Entries whose article is too thin to disambiguate among multiple NGIB
# homonyms. Typically one-liners of the form «Cot. Red. S. de España en
# la isla de Mallorca» without village, distance, jurisdiction or
# cross-reference. Marked with a distinct fallback label so they are
# distinguishable on the map from genuine island-centroid placements.
AMBIGUOUS_HOMONYMS = {
    ('Mallorca', 'SONSEGUI'),
    ('Mallorca', 'SON SUNER'),  # diacritics stripped: SÜÑER → SUNER
}

# Island centroid fallbacks (rough geographic centers, WGS84)
ISLAND_CENTROID = {
    'Mallorca':   (2.92, 39.60),
    'Menorca':    (4.10, 39.95),
    'Eivissa':    (1.43, 38.97),
    'Formentera': (1.45, 38.69),
    'Cabrera':    (2.93, 39.15),
}


import re

# Miñano editorial markers that are not part of the toponym. They must be
# stripped before fuzzy matching, otherwise titles such as
# "LLOSETA (adición)" lose against the 7-character "LLOSETA" entry under
# the length-disparity guard. The bracketed substantive qualifiers
# ((Isla de), (Pla de), (Nuestra Señora de) …) are preserved because they
# do disambiguate the toponym.
_EDITORIAL_SUFFIX_RX = re.compile(
    r'\s*(?:[—–-]\s*)?\((?:adici[oó]n|adiciones|adicion)\)\s*$', re.IGNORECASE
)
_EDITORIAL_TRAIL_RX = re.compile(
    r'\s*[—–-]\s*(?:adici[oó]n(?:es)?|coordenades|estad[ií]sticas? de aceite)\s*$',
    re.IGNORECASE,
)


def _strip_editorial(title: str) -> str:
    t = _EDITORIAL_SUFFIX_RX.sub('', title)
    t = _EDITORIAL_TRAIL_RX.sub('', t)
    return t.strip()


def best_match(title: str, island: str | None, gz_by_island: dict,
               entry_municipality: str | None = None):
    """Find the best (lon, lat) for a Miñano title.

    Strategy:
      - If the entry declares an island, the match must come from that island.
        Crossing islands has produced false positives (Eivissa's `es Fornells`
        wrongly matched against Menorca's `Fornells`, etc.), so the cross-island
        fallback is only used when the entry has no declared island.
      0. Curated override: a small table of explicit (island, title) →
         (lon, lat) for cases NGIB cannot disambiguate. Ambiguous-homonym
         titles raise an explicit sentinel handled by the caller.
      1. Exact normalized match → return its coords.
      2. Fuzzy WRatio match, prefer historical / municipi sources, and
         when the article declares a parent municipality, use it as a
         tiebreaker over otherwise equivalent homonyms.
      3. If a historical variant points to a modern form that itself lacks
         coords, fuzzy-match that modern form within the same island.
    """
    norm_title = normalize(_strip_editorial(title))
    if not norm_title or len(norm_title) < 3:
        return None

    island_ngib0 = ISLAND_ALIAS.get(island, island)

    # 0a. Ambiguous-homonym shortlist → signal caller to use centroid
    # fallback with an explicit label.
    if (island_ngib0, norm_title) in AMBIGUOUS_HOMONYMS:
        return {'_ambiguous_homonym': True}

    # 0b. Curated override → explicit coords.
    override = CURATED_OVERRIDES.get((island_ngib0, norm_title))
    if override:
        lon, lat, label = override
        return {'lon': lon, 'lat': lat,
                'matched': label, 'score': 100,
                'curated': True}

    island_ngib = island_ngib0

    # Candidate pools. When the declared island is known we restrict the
    # search to that island; only when no island is declared (or the alias
    # maps to None, e.g. for Balearic-wide articles) do we search the whole
    # archipelago.
    pools = []
    if island_ngib and island_ngib in gz_by_island:
        pools.append(gz_by_island[island_ngib])
    else:
        pools.append([r for rows in gz_by_island.values() for r in rows])

    # When the article declares its parent municipality (e.g. SON-LLUCH
    # depends on Palma), use it to break ties between otherwise equivalent
    # NGIB homonyms.
    entry_mun_norm = normalize(entry_municipality) if entry_municipality else ''

    def resolve_to_coords(r, score, pool):
        """r is a gazetteer row; return coords if found, else fuzzy-match its
        municipality (modern Catalan form) against the same island pool."""
        if r['lon'] is not None and r['lat'] is not None:
            return {'lon': r['lon'], 'lat': r['lat'],
                    'matched': r['spelling'], 'score': round(score, 1)}
        mun_target = r.get('mun')
        if not mun_target:
            return None
        # Exact spelling match first, within the same island pool.
        for r2 in pool:
            if r2.get('spelling') == mun_target and r2['lon'] is not None:
                return {'lon': r2['lon'], 'lat': r2['lat'],
                        'matched': r2['spelling'], 'score': round(score, 1)}
        # Fuzzy match on the modern municipality, still within the same pool.
        norm_mun = normalize(mun_target)
        choices2 = [r2['norm'] for r2 in pool if r2['lon'] is not None]
        meta2 = [r2 for r2 in pool if r2['lon'] is not None]
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

    def municipality_match(r):
        """True when this gazetteer row belongs to the article's declared
        parent municipality. Used as a tiebreaker among homonyms."""
        if not entry_mun_norm:
            return False
        return normalize(r.get('mun') or '') == entry_mun_norm

    for pool in pools:
        # 1. Exact normalized match
        exact = [r for r in pool if r['norm'] == norm_title]
        if exact:
            # Order of preference:
            #   (a) row whose municipality matches the article's declared
            #       parent (disambiguates Son Lluc-of-Palma from Son Lluc-of-Andratx)
            #   (b) historical (curated) entries
            #   (c) Municipi/Capital types
            exact.sort(key=lambda r: (
                not municipality_match(r),
                r['source'] != 'historical',
                'Municipi' not in (r.get('local_type') or ''),
            ))
            res = resolve_to_coords(exact[0], 100, pool)
            if res:
                return res

        # 2. Fuzzy match.
        # WRatio gives a perfect partial score when one string is a
        # substring of the other (e.g. "ROJA" inside "ALCARIA ROJA" scores
        # 90), which produces spurious matches against short toponyms.
        # We filter candidates so that the shorter of the two normalized
        # strings is at least 60% the length of the longer one.
        min_len = max(4, int(len(norm_title) * 0.6))
        choices_filtered = [
            (i, r['norm']) for i, r in enumerate(pool)
            if len(r['norm']) >= min_len
        ]
        if choices_filtered:
            idx_map = [i for i, _ in choices_filtered]
            choices = [c for _, c in choices_filtered]
            # Collect every candidate above cutoff and prefer one whose
            # municipality matches the article's declared parent.
            results = process.extract(
                norm_title, choices, scorer=fuzz.WRatio,
                score_cutoff=88, limit=10,
            )
            if results:
                results.sort(key=lambda t: (
                    not municipality_match(pool[idx_map[t[2]]]),
                    -t[1],
                ))
                _, score, local_idx = results[0]
                r = pool[idx_map[local_idx]]
                res = resolve_to_coords(r, score, pool)
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

            mat = (e.get('stats', {}) or {}).get('contribuye_con') or e.get('municipality')
            match = best_match(title, island, gz, entry_municipality=mat)
            if match and not match.get('_ambiguous_homonym'):
                emit(match)
                n_matched += 1
                continue

            # Branch: known-ambiguous title → straight to island centroid
            # with a distinct label so it is visible as «ubicació
            # indeterminada» on the map.
            if match and match.get('_ambiguous_homonym'):
                island_ngib = ISLAND_ALIAS.get(island)
                if island_ngib and island_ngib in ISLAND_CENTROID:
                    lon, lat = ISLAND_CENTROID[island_ngib]
                    emit({
                        'lon': lon, 'lat': lat,
                        'matched': f'(ubicació indeterminada · {island_ngib})',
                        'score': 0,
                        'fallback': 'ambiguous-homonym',
                    })
                    n_matched += 1
                    continue

            # Fall back to matriz from "contribuye_con" or "municipality"
            if mat:
                match = best_match(mat, island, gz)
                if match and not match.get('_ambiguous_homonym'):
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
