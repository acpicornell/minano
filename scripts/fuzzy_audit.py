#!/usr/bin/env python3
"""Comprehensive fuzzy audit: find ALL Balearic articles missed by Phase 1 indexer.

Strategy:
1. Walk every paragraph of every tomo's chocr.
2. Use the `regex` library's fuzzy matching `(?:word){e<=N}` to detect
   OCR-mangled mentions of Balearic anchors in the first ~400 chars of body.
3. Score each paragraph by how many distinct anchors it hits.
4. Filter out strong anti-balear signals (other provinces, Galicia parishes, etc.).
5. Deduplicate against entries already in data/text/page_*.json.
6. Output candidates as a TSV for staging.

Run:  python3 scripts/fuzzy_audit.py [--min-score 2] [--limit 500]
"""
import argparse, gzip, json, re as stdlib_re, sys
from pathlib import Path
from collections import defaultdict

import regex as rx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from index_volume import iter_paragraphs  # type: ignore

# --- Strong-positive Balearic anchors (fuzzy with e<=1 or 2) -----------------
# (anchor_word, max_edit_dist, weight)
POS_ANCHORS = [
    # Island-canonical: usually appears as "isla de Mallorca" or "obispado de Mallorca"
    ('Mallorca',   1, 3),
    ('Mallorea',   1, 3),  # OCR variant of Mallorca
    ('Menorca',    1, 3),
    ('Mahón',      1, 3),
    ('Mahon',      1, 3),
    ('Ibiza',      1, 3),
    ('Iviza',      1, 3),
    ('Formentera', 2, 3),
    ('Cabrera',    1, 2),  # weaker — many peninsular Cabreras
    ('Baleares',   1, 3),
    ('Balear',     1, 2),
    ('Pitiusa',    1, 3),
    ('Pithiusa',   1, 3),
    # Capital cities (also indicates Balearic context if mentioned in body)
    ('Palma',      1, 2),  # many other Palmas — but in Balearic context strong
    ('Ciudadela',  1, 2),
    ('Iviza',      1, 3),
    ('Alcudia',    1, 2),
    # Common Balearic locator phrases — these are anchors when "isla" precedes
    # We'll match "isla de Mallorca" etc. directly below.
]

# Phrase-level anchors — very strong evidence (worth more weight)
PHRASE_ANCHORS = [
    (r'(?:islas? de Mallorca){e<=2}',      4),
    (r'(?:islas? de Menorca){e<=2}',       4),
    (r'(?:islas? de Iviza){e<=2}',         4),
    (r'(?:islas? de Ibiza){e<=2}',         4),
    (r'(?:isla y obispado de Mallorca){e<=3}', 5),
    (r'(?:isla y obispado de Menorca){e<=3}',  5),
    (r'(?:obispado de Mallorca){e<=2}',    4),
    (r'(?:obispado de Menorca){e<=2}',     4),
    (r'(?:provincia de Mallorca){e<=2}',   4),
    (r'(?:provincia de Menorca){e<=2}',    4),
    (r'(?:provincia de Iviza){e<=2}',      4),
    (r'(?:provincia de Ibiza){e<=2}',      4),
    (r'(?:en las Baleares){e<=2}',         4),
]

# Strong NEGATIVE anchors — if body contains these in first 250 chars, drop
NEG_ANCHORS = [
    'Galicia', 'Asturias', 'Cantabria', 'Vizcaya', 'Guipúzcoa', 'Navarra',
    'Álava', 'Alava', 'Aragón', 'Catalu', 'Cataluña', 'Cataluna',
    'Valencia,', 'Valencia.', 'Murcia', 'Granada', 'Sevilla', 'Córdoba',
    'Cordoba', 'Jaén', 'Almería', 'Almeria', 'Málaga', 'Malaga',
    'Cádiz', 'Cadiz', 'Huelva', 'Castilla', 'León,', 'Leon,', 'Palencia',
    'Burgos', 'Soria', 'Segovia', 'Ávila', 'Avila', 'Salamanca', 'Zamora',
    'Valladolid', 'Toledo', 'Madrid', 'Guadalajara', 'Cuenca,', 'Cuenca.',
    'Albacete', 'La Mancha', 'la Mancha', 'Mancha,', 'Mancha.', 'Estremadura',
    'Extremadura', 'Badajoz', 'Cáceres', 'Caceres', 'Tenerife', 'Canarias',
    'Portugal', 'Beyra', 'Alentejo', 'Algarve',
]

# Anti-balear if MULTIPLE non-balear province names appear
def neg_score(text):
    n = 0
    for w in NEG_ANCHORS:
        if w in text:
            n += 1
            if n >= 1: break  # one strong negative usually enough
    return n

def normalize(par):
    n = rx.sub(r'\s+', ' ', par).strip()
    n = rx.sub(r'(\w)-(\w)', r'\1\2', n)
    return n

def score_paragraph(body):
    """Return total positive score, list of matched anchors."""
    score = 0
    matched = []
    body_head = body[:600]
    # word-level fuzzy anchors
    for word, k, w in POS_ANCHORS:
        if rx.search(rf'(?:{rx.escape(word)}){{e<={k}}}', body_head, rx.IGNORECASE):
            score += w
            matched.append(word)
    # phrase-level
    for pat, w in PHRASE_ANCHORS:
        if rx.search(pat, body_head, rx.IGNORECASE):
            score += w
            matched.append(pat)
    return score, matched

def is_likely_headword_paragraph(body):
    """Heuristic: paragraph starts with CAPS+name+,?\\s*(typology abbrev)."""
    head = body[:100]
    # Tomo XI suplemento is different — starts with mixed-case word (e.g. "Sincu.")
    # We accept both styles.
    if rx.match(r'^[A-ZÑÁÉÍÓÚÜ][A-ZÑÁÉÍÓÚÜa-záéíóúñç\(\)\.\-\s]{2,60}[,\.]', head):
        return True
    return False

def extract_title(body):
    """Pull out the headword (everything up to first comma or period)."""
    head = body[:120]
    m = rx.match(r'^([^,\.;]+)[,\.;]', head)
    if m:
        return m.group(1).strip()
    return head.split()[0] if head.split() else '?'

def load_existing_titles():
    """Return set of (vol, leaf) tuples already extracted."""
    done = set()
    for p in (ROOT / 'data' / 'text').glob('page_*.json'):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        done.add((d.get('vol'), int(d.get('leaf', -1))))
    return done

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-score', type=int, default=5)
    ap.add_argument('--limit', type=int, default=2000)
    ap.add_argument('--include-done', action='store_true',
                    help='also include leaves already extracted')
    ap.add_argument('--output', default='data/fuzzy_candidates.tsv')
    args = ap.parse_args()

    done_leaves = load_existing_titles() if not args.include_done else set()
    print(f'Skipping {len(done_leaves)} leaves already extracted', file=sys.stderr)

    rows = []  # (score, vol, leaf, title, snippet, matched)
    for vol in ['01','02','03','04','05','06','07','08','09','10','11']:
        chocr = ROOT / 'data' / 'chocr' / f'tomo{vol}.html.gz'
        if not chocr.exists():
            continue
        print(f'== Tomo {vol} ==', file=sys.stderr)
        n_seen = n_kept = 0
        for leaf, par in iter_paragraphs(chocr):
            if leaf is None or not par:
                continue
            if (vol, leaf) in done_leaves:
                continue
            body = normalize(par)
            n_seen += 1
            if len(body) < 60:
                continue
            if not is_likely_headword_paragraph(body):
                continue
            score, matched = score_paragraph(body)
            if score < args.min_score:
                continue
            if neg_score(body[:300]) >= 1 and score < args.min_score + 4:
                # negative ambient — need stronger positive
                continue
            title = extract_title(body)
            snippet = body[:200].replace('\t', ' ')
            rows.append((score, vol, leaf, title, snippet, ','.join(matched[:5])))
            n_kept += 1
            if len(rows) >= args.limit:
                break
        print(f'   {vol}: {n_seen} paragraphs scanned, {n_kept} kept', file=sys.stderr)
        if len(rows) >= args.limit:
            break

    # Sort by score desc then (vol, leaf)
    rows.sort(key=lambda r: (-r[0], r[1], r[2]))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w') as f:
        f.write('score\tvol\tleaf\ttitle\tsnippet\tmatched\n')
        for r in rows:
            f.write('\t'.join(str(x) for x in r) + '\n')
    print(f'\nWrote {len(rows)} candidates to {out}', file=sys.stderr)

    # Dedupe by (vol, leaf) — for staging
    by_leaf = {}
    for r in rows:
        key = (r[1], r[2])
        if key not in by_leaf or by_leaf[key][0] < r[0]:
            by_leaf[key] = r
    print(f'Distinct (vol, leaf): {len(by_leaf)}', file=sys.stderr)

if __name__ == '__main__':
    main()
