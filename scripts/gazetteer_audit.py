#!/usr/bin/env python3
"""Audit Miñano's chocr against the Balearic gazetteer.

Strategy:
1. Load gazetteer (data/gazetteer.parquet) — ~22,800 normalized Balearic
   toponyms with metadata (island, municipality, type, source).
2. For each paragraph in each tomo's chocr, extract the "title head" —
   the leading capitalised run before the first comma or period.
3. Normalise it (same pipeline as the gazetteer: strip article, NFD-strip
   diacritics, uppercase, collapse whitespace).
4. Fuzzy-search the gazetteer with `rapidfuzz.process.extractOne` using
   WRatio (token-aware) — matches single-word and multi-word toponyms.
5. Apply an adaptive score cutoff based on title length:
       len ≤ 5  → score ≥ 92
       len ≤ 8  → score ≥ 85
       len ≤ 12 → score ≥ 80
       else     → score ≥ 75
6. Dedupe against entries we already have (data/text/page_*.json).
7. Output ranked candidates → data/gazetteer_candidates.tsv.

We *do not* require a positive Balearic anchor in the body, because the
gazetteer match itself IS the anchor (we know the toponym is Balearic
because it's in NGIB). This is exactly the recall improvement we need.
"""
from __future__ import annotations

import argparse, json, sys, unicodedata
from pathlib import Path
from collections import defaultdict

import duckdb
import regex as rx
from rapidfuzz import process, fuzz

# Reuse iter_paragraphs from the existing indexer.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from index_volume import iter_paragraphs  # type: ignore
from build_gazetteer import normalize       # same normalisation as gazetteer

GAZETTEER = ROOT / 'data' / 'gazetteer.parquet'
DEFAULT_OUT = ROOT / 'data' / 'gazetteer_candidates.tsv'

# Adaptive cutoffs by title length (after normalisation).
def score_cutoff(title_len: int) -> int:
    if title_len <= 5:  return 95   # very short: easy to false-match
    if title_len <= 8:  return 90
    if title_len <= 12: return 85
    return 80


# ---- Body anchors -----------------------------------------------------------
# These patterns establish that the paragraph is ABOUT a Balearic place. The
# key constraint: each pattern must contain an EXPLICIT Balearic place name
# (Mallorca/Menorca/Iviza/Ibiza/Formentera/Cabrera/Baleares/Palma/Mahon/etc.)
# so we can't be fooled by generic phrases like "Esp., provincia de…" + e<=3.
# Edit distance kept at 1 (occasional OCR error) — 2+ allows too many false
# matches against e.g. "Mancha" → "Mallorca" with e<=4.
POS_BODY_PATTERNS = [
    # Explicit "in island of X" — strongest signal.
    r'(?:isla\s+de\s+Mallorca){e<=1}',
    r'(?:isla\s+de\s+Menorca){e<=1}',
    r'(?:isla\s+de\s+I[vb]i[zs]a){e<=1}',
    r'(?:isla\s+de\s+Cabrera){e<=1}',
    r'(?:isla\s+de\s+Formentera){e<=1}',
    # Diocese / province phrasing.
    r'(?:obispado\s+de\s+Mallorca){e<=1}',
    r'(?:obispado\s+de\s+Menorca){e<=1}',
    r'(?:provincia\s+de\s+Mallorca){e<=1}',
    r'(?:provincia\s+de\s+Menorca){e<=1}',
    r'(?:provincia\s+de\s+I[vb]i[zs]a){e<=1}',
    # "X de la isla y obispado de Y" — Miñano's standard heading.
    r'(?:isla\s+y\s+obisp(?:ado)?\s+de\s+Mallorca){e<=2}',
    r'(?:isla\s+y\s+obisp(?:ado)?\s+de\s+Menorca){e<=2}',
    # "Iviza/Ibiza" alone is balearic — no false-positive equivalent
    # elsewhere in Spain.
    r'\b(?:Iviza|Ibiza)\b',
    # Caserío de Esp., provincia de Iviza (standard Eivissa formula)
    r'(?:caserío\s+de\s+(?:Esp|España)\s*,\s*provincia\s+de\s+I[vb]i[zs]a){e<=2}',
    # General balearic anchors
    r'\b(?:islas?\s+Baleares)\b',
    r'\b(?:Baleares)\b',
    r'\b(?:Pithiusas?|Pitiusas?)\b',
    # Eivissan administrative quartones
    r'(?:cuartón\s+de\s+(?:Esp|España).{0,40}Iviza){e<=2}',
    # Reference-back to Balearic matriz
    r'(?:contribuye\s+con\s+(?:Palma|Manacor|Felanitx|Petra|Selva|Sineu|Soller|Muro|Artá|Inca|Llucmajor|Algaida|Bunyola|Buñola)){e<=2}',
    r'(?:matriz\s+(?:Palma|Manacor|Felanitx|Petra|Sineu|Soller|Muro|Artá|Inca|Llucmajor|Algaida|Bunyola|Buñola|Santanyí|Pollensa)){e<=2}',
    r'(?:aneja\s+(?:de|del|de\s+la)\s+(?:Petra|Manacor|Sineu|Soller|Esporlas|Palma|Felanitx|Santanyí|Muro|Mercadal|Mahón|Mahon)){e<=2}',
]

# Strong negative — words/phrases that establish NON-Balearic context. Each
# is checked as a word-boundary regex so "León" matches "León," / "León."
# but not part of a longer word.
NEG_WORDS = (
    'Galicia', 'Asturias', 'Cantabria', 'Vizcaya', 'Guipúzcoa', 'Navarra',
    'Álava', 'Alava', 'Aragón',
    'Murcia', 'Granada', 'Sevilla', 'Córdoba', 'Cordoba',
    'Jaén', 'Almería', 'Almeria', 'Málaga', 'Malaga',
    'Cádiz', 'Cadiz', 'Huelva', 'Castilla',
    'Palencia', 'Burgos', 'Soria', 'Segovia', 'Ávila', 'Avila',
    'Salamanca', 'Zamora', 'Valladolid', 'Madrid', 'Guadalajara',
    'Albacete', 'Estremadura', 'Extremadura', 'Badajoz', 'Cáceres', 'Caceres',
    'Tenerife', 'Canarias', 'Gomera', 'Hierro', 'Lanzarote', 'Fuerteventura',
    'Portugal', 'Alentejo', 'Algarve',
    'León',  # bare, word-boundary
    'Tuy', 'Lugo', 'Orense', 'Pontevedra', 'Mondoñedo', 'Santiago',
    'Toledo', 'Cuenca',
)
NEG_PHRASES = (
    'provincia de Valencia', 'provincia de Cataluña', 'provincia de Catalu',
    'prov. de Valencia', 'prov. de Cataluña', 'prov. de Catalu',
    'prov. de Aragón', 'prov. de Aragon',
    'prov. de Estremadura', 'prov. de Extremadura',
    'prov. y part. de Valencia',
    'arzobispado de Toledo', 'arzobispado de Sevilla', 'arzobispado de Burgos',
    'en Galicia', 'en Castilla', 'en Asturias', 'en Aragón',
    'en Navarra', 'en Andalucia',
    'concejo de', 'corregimiento de Lérida', 'corregimiento de Mataró',
    'corregimiento de Villafranca', 'corregimiento de Vich',
    'corregimiento de Gerona', 'corregimiento de Manresa',
    'corregimiento de Puigcerdá',
    'partido de Talavera', 'partido de Lérida',
    'feligresía', 'Felig.',          # Galician-only typology
    'jurisdicción de Galicia',
    'la Mancha', 'La Mancha',
    'Reino de Galicia',
)


def _strip_acc(s: str) -> str:
    n = unicodedata.normalize('NFD', s)
    return ''.join(c for c in n if unicodedata.category(c) != 'Mn')


_NEG_WORD_RE = rx.compile(
    r'\b(?:' + '|'.join(rx.escape(_strip_acc(w)) for w in NEG_WORDS) + r')\b',
    rx.IGNORECASE,
)
_NEG_PHRASES_NORM = [_strip_acc(p).lower() for p in NEG_PHRASES]


def _despace_ocr(s: str) -> str:
    """Repair common OCR glue: insert missing spaces after particles
    ('de', 'del', 'la', 'en', 'y') when immediately followed by a capital
    letter. So 'deCataluña' → 'de Cataluña', 'enGalicia' → 'en Galicia'."""
    return rx.sub(r'(?<=\b(?:de|del|la|el|en|y|sobre|hasta|por)\s?)([A-ZÑÁÉÍÓÚÜ])',
                  r' \1', s)


def body_has_positive(body: str) -> bool:
    head = _despace_ocr(body[:600])
    for pat in POS_BODY_PATTERNS:
        if rx.search(pat, head, rx.IGNORECASE):
            return True
    return False


def body_has_negative(body: str) -> bool:
    """Check the first 500 chars (de-spaced, accent-stripped, lowercased)
    for any non-Balearic regional anchor."""
    head = _strip_acc(_despace_ocr(body[:600])).lower()
    if _NEG_WORD_RE.search(head):
        return True
    for w in _NEG_PHRASES_NORM:
        if w in head:
            return True
    return False


# Heuristic: paragraph looks like a Miñano-style entry head if it starts
# with at least 2 chars of CAPS followed by a comma, period, or space-CAPS.
HEADWORD_RE = rx.compile(
    r'^\s*([A-ZÑÁÉÍÓÚÜÀÈÌÒÙÇ][A-ZÑÁÉÍÓÚÜÀÈÌÒÙÇa-záéíóúñçü\(\)\'^_\.\s\-]{1,80}?)\s*[,\.;:]',
)

# Allow lowercase opening for the Suplemento (Tomo XI uses mixed-case heads
# like "Sincu." / "Mancor.").
HEADWORD_RE_SUPL = rx.compile(
    r'^\s*([A-ZÑÁÉÍÓÚÜÀÈÌÒÙÇ][A-Za-záéíóúñçü\(\)\'^_\.\s\-]{1,80}?)\s*[,\.;:]',
)


def extract_title(body: str, is_supl: bool) -> str | None:
    pat = HEADWORD_RE_SUPL if is_supl else HEADWORD_RE
    m = pat.match(body)
    if not m:
        return None
    head = m.group(1).strip()
    # Drop trailing parenthetical (e.g. "PALMA (de Mallorca)" → "PALMA")
    head = rx.sub(r'\s*\([^)]*\)\s*$', '', head)
    head = head.strip(' .,;:-_^')
    if len(head) < 3:
        return None
    return head


def load_gazetteer(strict: bool = True):
    """Load gazetteer rows.

    strict=True (default): keep only HIGH-PRECISION types — municipalities,
    villages (barris), historical Castilian variants, religious sites with
    a unique-ish name, and major natural features (Cabrera, Dragonera).
    Drops the ~11k generic possessions ("sa Cabana", "Es Bosquet",
    "n'Espanya") that swamp the matcher with peninsular false positives.

    strict=False: include every NGIB entry.
    """
    con = duckdb.connect(':memory:')
    if strict:
        # Note: the 'Finca, possessió' entries are mostly small estates
        # whose names match common Castilian words. We only keep the very
        # specific ones (those with a distinct 'Son X' / 'Cas X' /
        # 'S\'X' prefix indicating a Mallorcan possession nomenclature).
        sql = f"""
            SELECT normalized, spelling, municipality, island, local_type,
                   is_settlement, source
            FROM read_parquet('{GAZETTEER}')
            WHERE local_type IN (
                  'Variant històrica',
                  'Municipi', 'Capital de municipi', 'Capital de Municipi',
                  'Vila',
                  'Barri', 'Barriada',
                  'Urbanització, barriada (aïllat)',
                  'Entitat de Població',
                  'Llogaret, llogarret, ranxo',
                  'Església, capella, oratori, ermita',
                  'Monestir, convent, cartoixa',
                  'Edifici religiós',
                  'Castell, fortalesa', 'Far',
                  'Illa, illot, escull'
              )
              OR (
                  local_type = 'Finca, possessió, lloc, casa pagesa, caseta'
                  AND (
                       spelling LIKE 'Son %' OR spelling LIKE 'Sa %' OR
                       spelling LIKE 'sa %' OR spelling LIKE 'Ses %' OR
                       spelling LIKE 'ses %' OR spelling LIKE 'Es %' OR
                       spelling LIKE 'es %' OR spelling LIKE 'Can %' OR
                       spelling LIKE 'Cas %' OR spelling LIKE 'Bini%' OR
                       spelling LIKE 'Llu%' OR spelling LIKE 'Alca%'
                  )
              )
        """
    else:
        sql = f"""
            SELECT normalized, spelling, municipality, island, local_type,
                   is_settlement, source
            FROM read_parquet('{GAZETTEER}')
        """
    rows = con.sql(sql).fetchall()
    choices = [r[0] for r in rows]
    meta = rows
    bucket = defaultdict(list)
    for i, c in enumerate(choices):
        if len(c) >= 3:
            bucket[c[:3]].append(i)
    return choices, meta, bucket


def load_done_leaves():
    """Set of (vol, leaf) we already have a JSON for."""
    done = set()
    for p in (ROOT / 'data' / 'text').glob('page_*.json'):
        try:
            d = json.loads(p.read_text())
            done.add((d['vol'], int(d['leaf'])))
        except Exception:
            continue
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=2000)
    ap.add_argument('--output', default=str(DEFAULT_OUT))
    ap.add_argument('--include-done', action='store_true',
                    help='also include already-extracted leaves')
    ap.add_argument('--show-buckets', action='store_true')
    args = ap.parse_args()

    print('Loading gazetteer…', file=sys.stderr)
    choices, meta, bucket = load_gazetteer()
    print(f'  {len(choices):,} entries', file=sys.stderr)
    if args.show_buckets:
        # Show top buckets to assess key skew
        sizes = sorted([(k, len(v)) for k, v in bucket.items()], key=lambda x: -x[1])
        for k, n in sizes[:20]:
            print(f'  bucket {k!r:>6}  {n:>5} entries', file=sys.stderr)

    done = load_done_leaves() if not args.include_done else set()
    print(f'Skipping {len(done)} already-extracted leaves', file=sys.stderr)

    candidates = []
    for vol in ('01','02','03','04','05','06','07','08','09','10','11'):
        chocr = ROOT / 'data' / 'chocr' / f'tomo{vol}.html.gz'
        if not chocr.exists():
            continue
        print(f'\n== Tomo {vol} ==', file=sys.stderr)
        is_supl = (vol == '11')
        n_para = n_titled = n_matched = 0
        for leaf, par in iter_paragraphs(chocr):
            if leaf is None or not par:
                continue
            if (vol, leaf) in done:
                continue
            # Same de-hyphen + whitespace normalisation as the indexer.
            body = rx.sub(r'\s+', ' ', par).strip()
            body = rx.sub(r'(\w)-(\w)', r'\1\2', body)
            if len(body) < 30:
                continue
            n_para += 1

            title = extract_title(body, is_supl)
            if not title:
                continue
            n_titled += 1

            norm_title = normalize(title)
            if not norm_title or len(norm_title) < 3:
                continue

            # Bucket pre-filter: only consider gazetteer entries whose
            # first 3 normalised chars share at least 1 character with
            # the title's. (Approximates a 1-edit prefix tolerance.)
            prefix = norm_title[:3]
            buck_idx = set(bucket.get(prefix, []))
            # Also include prefixes within 1 char swap (alphabet-ordered).
            for i in range(3):
                for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZÑ':
                    if c == prefix[i]:
                        continue
                    var = prefix[:i] + c + prefix[i+1:]
                    if var in bucket:
                        buck_idx.update(bucket[var])
            if not buck_idx:
                # No bucket → fall back to full gazetteer (slow path)
                buck_idx = set(range(len(choices)))

            # Fuzzy match restricted to the bucket.
            sub_choices = [choices[i] for i in buck_idx]
            # rapidfuzz.process.extractOne returns (best, score, index_into_sub)
            best = process.extractOne(
                norm_title, sub_choices,
                scorer=fuzz.WRatio,
                score_cutoff=70,  # broad initial cut; refine later
            )
            if not best:
                continue
            best_norm, score, local_idx = best
            cutoff = score_cutoff(len(norm_title))
            if score < cutoff:
                continue
            # Two-tier filtering:
            #   tier A (high precision): gazetteer + body has positive balearic anchor
            #   tier B (mid  precision): gazetteer + no peninsular negative anchor
            # Tier A candidates are very likely real; tier B need manual review.
            if body_has_negative(body):
                continue   # peninsular — drop in all cases
            tier = 'A' if body_has_positive(body) else 'B'
            # Resolve back to original gazetteer row
            gaz_idx = list(buck_idx)[local_idx]
            (_, spelling, mun, isl, ltype, is_sett, src) = meta[gaz_idx]
            n_matched += 1
            candidates.append({
                'tier': tier,
                'score': round(score, 1),
                'vol': vol,
                'leaf': leaf,
                'title_raw': title,
                'title_norm': norm_title,
                'gaz_spelling': spelling,
                'gaz_norm': best_norm,
                'island': isl or '',
                'municipality': mun or '',
                'local_type': ltype or '',
                'is_settlement': bool(is_sett),
                'source': src or '',
                'snippet': body[:160],
            })
            if len(candidates) >= args.limit:
                break
        print(f'   {vol}: paras={n_para}, with-title={n_titled}, matched={n_matched}',
              file=sys.stderr)
        if len(candidates) >= args.limit:
            break

    # Sort: tier A first, then score desc, then settlement, vol, leaf
    candidates.sort(key=lambda c: (c['tier'], -c['score'],
                                    not c['is_settlement'],
                                    c['vol'], c['leaf']))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ['tier','score','vol','leaf','title_raw','title_norm','gaz_spelling',
            'island','municipality','local_type','is_settlement','source','snippet']
    with out_path.open('w') as f:
        f.write('\t'.join(cols) + '\n')
        for c in candidates:
            f.write('\t'.join(str(c[k]) for k in cols) + '\n')

    print(f'\nWrote {len(candidates):,} candidates → {out_path}', file=sys.stderr)

    # Quick summary
    n_a = sum(1 for c in candidates if c['tier'] == 'A')
    n_b = sum(1 for c in candidates if c['tier'] == 'B')
    n_sett = sum(1 for c in candidates if c["is_settlement"])
    print(f'\nTier A (high precision): {n_a}', file=sys.stderr)
    print(f'Tier B (medium, review): {n_b}', file=sys.stderr)
    print(f'Settlements only:        {n_sett}', file=sys.stderr)
    by_isl = defaultdict(int)
    by_vol = defaultdict(int)
    for c in candidates:
        if c['is_settlement']:
            by_isl[c['island']] += 1
            by_vol[c['vol']] += 1
    print('\nSettlement matches by island:', file=sys.stderr)
    for isl, n in sorted(by_isl.items(), key=lambda x: -x[1]):
        print(f'  {isl or "(unknown)":<14} {n}', file=sys.stderr)
    print('\nSettlement matches by tomo:', file=sys.stderr)
    for vol, n in sorted(by_vol.items()):
        print(f'  tomo {vol}  {n}', file=sys.stderr)

if __name__ == '__main__':
    main()
