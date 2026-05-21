# Miñano, Balearic subset

A re-digitisation of the **Balearic Islands subset** of Sebastián de
Miñano y Bedoya's *Diccionario geográfico-estadístico de España y
Portugal* (Madrid, 1826–1829, 11 vols.).

Sister project of [`../madoz`](../madoz). Madoz (1845–1850) is the
canonical Spanish geographical dictionary of the mid-19th century;
Miñano is its older sibling and the source Madoz himself corrects and
expands. Reading them side by side lets us watch a place enter or
leave the official record, watch population figures shift over two
decades, and watch the abbreviation conventions of Spanish geography
crystallise into Madoz's familiar style.

## Goals

Same shape as madoz, tuned to Miñano's idiosyncrasies:

- A clean transcription of each Balearic entry's body, preserving
  Miñano's abbreviation style (`V. R. de Esp., en la isla de
  Mallorca`, `A. O.`, `A. P.`, `vec.`, `hab.`, `Contr. con Palma`).
- Volume / leaf / printed-page metadata so each entry can be cited as
  *"Miñano, t. II, p. 123"* and verified against the IA facsimile.
- Structured place metadata (place_type, island, dependency
  municipality) where the article supports it.
- Structured statistics (vecinos, almas, contribución) when they
  appear inline in the prose.

## What's already here, what isn't

This project is **early-stage**. So far:

- Phase 1 (deterministic indexing) is implemented and validated on
  **all 11 tomos** (I-XI, with V and X via the ABBYY-derived chOCR
  recipe; see "ABBYY-derived chOCR" below): **82 Balearic articles**
  identified (`scripts/index_volume.py` +
  `scripts/purge_non_balearic.py`). Distribution: ~60+ Mallorca,
  ~10 Menorca, ~5 Ibiza (Formentera and Cabrera-islet bundled into
  Mallorca by the by-island heuristic).
- The OCR-tolerance patterns in PAT_BALEAR_CANON / PAT_STRONG_BALEAR
  evolved as we expanded coverage. Iterations so far:
  fuzzy place-name patterns (Mallorca / Menorca / Ibiza / Iviza /
  Formentera / Cabrera / Baleares with each character class widened
  for OCR noise), then `Illa` (Catalan-style spelling Miñano
  occasionally uses) and `pror.` (BSB-scan mangle of `prov.`) added
  during Tomo IX. The purge correctly drops peninsular homonyms
  (Cabrera-of-León, BERMEO of Vizcaya, CASJLLAS of Salamanca, VILLAR
  DEL MONTE of León, …).
- A Phase-1c OCR-title fix pass (`scripts/fix_ocr_titles.py`, port of
  madoz's `fix_ocr_*_titles.py` family) carries a hand-curated FIXES
  table of ``(vol, leaf, old, new, comment)`` rows that correct
  unambiguous OCR misreads (``BEL VER`` → ``BELVER``, ``BUGEU`` →
  ``BUGER``) while preserving Miñano's authentic spellings. Each
  fix's source-of-truth is documented inline. Additionally, the
  indexer's title regex now tolerates ``^_`` mid-toponym with a
  post-strip pass, so ``CABRER^A (Isla de)`` (the Cabrera-islet
  article that was previously missed) is now recovered as
  ``CABRERA (Isla de)`` without any hand-curated entry.
- Phase 3 (LLM extraction) is implemented in
  `scripts/extract_text.py` and validated on all 10 leaves of Tomo II
  for $0.25 total (Claude Sonnet 4.6, 13/13 entries, 0 low-confidence
  results). The script sends each leaf's chocr text plus a 1-leaf
  continuation window to Claude with a tool-use schema that captures
  ``title``, ``place_type``, ``island``, ``seigneurial_regime``,
  ``mayor_type``, ``municipality``, ``description``, ``stats``,
  ``cross_references`` and ``confidence``. Output: one
  ``data/text/page_<vol>_<leaf>.json`` per leaf.
- Phases 4 (DB build) and 5 (web export) are wired up:
  `scripts/load_text.py` flattens the per-leaf JSONs into
  `db/minano.duckdb`'s `text_entries` table, and
  `scripts/export_web_data.py` joins the DB row → IA-facsimile URL
  via the per-tomo identifier and writes a compact
  `web/data.json` (~11 KB, 13 entries). The static site
  (`web/index.html` + `web/app.js` + `web/style.css`, vanilla JS,
  no framework, no DuckDB-WASM) consumes that JSON directly.
- The Suplemento (Tomo XI, ``diccionariogeog00bedogoog``) was
  inspected and deliberately skipped as a starting point because its
  body is partitioned into "AL TOMO II.", "AL TOMO III.", … sections
  that restart alphabetically — atypical structure, harder to
  calibrate the indexer on.
- Phases 2–5 (cross-reference, Claude extraction, recovery, web
  export) — **not yet ported**.

The pipeline lives entirely in `scripts/`. Run from the repo root.

## Tomos · Internet Archive sources

The 11 volumes of Miñano's *Diccionario* are scattered across several
Internet Archive items, each digitised by a different library and
uploaded with a heterogeneous identifier (unlike madoz's regular
`diccionariogeogr<NN>mado` pattern). The table below lists the canonical
source we use per tomo, what alphabetical range it covers, and whether
Internet Archive serves the chOCR (the input the pipeline needs).

| Tomo | Year | Range | Identifier (chOCR ✓) | Source library |
|---:|:-:|---|---|---|
| **I**   | 1826 | A – AZ        | [`diccionariogeogr01mi`](https://archive.org/details/diccionariogeogr01mi) | Univ. Toronto |
| **II**  | 1826 | BAB – CAS     | [`diccionariogeogr02mi`](https://archive.org/details/diccionariogeogr02mi) | Univ. Toronto |
| **III** | 1826 | CAS – ESPADILLO | [`diccionariogeogr03mi`](https://archive.org/details/diccionariogeogr03mi) | Univ. Toronto |
| **IV**  | 1826 | ESP – HIT     | [`diccionariogeog01bedogoog`](https://archive.org/details/diccionariogeog01bedogoog) | Univ. Complutense |
| **V**   | 1826 | HIT – MEMBRIVE | [`diccionariogeog06machgoog`](https://archive.org/details/diccionariogeog06machgoog) † ABBYY-derived chOCR | Google scan |
| **VI**  | 1827 | (M – P)       | [`diccionariogeog05machgoog`](https://archive.org/details/diccionariogeog05machgoog) | Google scan |
| **VII** | 1827 | (P – S)       | [`diccionariogeog07machgoog`](https://archive.org/details/diccionariogeog07machgoog) | Google scan |
| **VIII**| 1827 | SAN – TEMPLE  | [`diccionariogeog04bedogoog`](https://archive.org/details/diccionariogeog04bedogoog) | Univ. Complutense |
| **IX**  | 1828 | TOR – VIL     | [`bub_gb_L1BIFQFZTHoC`](https://archive.org/details/bub_gb_L1BIFQFZTHoC) | Bayerische Staatsbibliothek |
| **X**   | 1828 | (VIL – Z)     | [`diccionariogeog02bedogoog`](https://archive.org/details/diccionariogeog02bedogoog) † ABBYY-derived chOCR ⚠ partial scan | Univ. Complutense |
| **XI**  | 1829 | Suplemento (AL TOMO I – AL TOMO X) | [`diccionariogeogr11mi`](https://archive.org/details/diccionariogeogr11mi) | Univ. Toronto |

Alternate scans we found (not used as primary source, but kept as
fallback in case the primary has problems):

- Tomo I:    `bub_gb_gNreJYQnDAIC` (Bavarian State Library)
- Tomo II:   `diccionariogeog03bedogoog` (Oxford — partial scan, ends at CASTRO)
- Tomo III:  `bub_gb_8P4RqRbrtxgC` (BSB), `diccionariogeog05bedogoog` (Complutense), `diccionariogeog08machgoog` (NYPL — partial)
- Tomo VIII: `diccionariogeog06bedogoog` (duplicate Complutense upload)
- Tomo X:    `bub_gb_cXvCiGZrauYC` (BSB Naples scan — also partial, ~624 KB djvu)
- Tomo XI:   `diccionariogeog00bedogoog` (Complutense — used by us initially as the linked starting point)

### † ABBYY-derived chOCR

For Tomos V and X, Internet Archive does **not** serve a
``chocr.html.gz`` directly — but it does serve the underlying ABBYY
FineReader v6 XML as ``_abbyy.gz``. IA derives its chocr from this
file using its own open-source toolchain
([`archive-hocr-tools`](https://github.com/internetarchive/archive-hocr-tools)),
so we can do the same locally and produce a chocr that is
**bit-for-bit equivalent** to what IA would serve. The recipe lives
in `scripts/derive_chocr_from_abbyy.py`:

1. Download ``<identifier>_abbyy.gz`` from IA.
2. Decompress to plain ABBYY FineReader v6 XML.
3. Run ``abbyy-to-hocr`` (from `archive-hocr-tools`).
4. Gzip the resulting hOCR to ``data/chocr/tomo<vol>.html.gz`` — our
   pipeline reads it unchanged.
5. Run ``hocr-pagenumbers`` for the leaf→printed-page map.

Throughput: ~5-15 seconds per tomo. OCR quality identical to
IA-served chocr (it's the same ABBYY output, just re-packaged).

For **Tomo V** this recovers the critical landmark articles:
**INCA**, **MAHON** (× 2: término + ciudad), **MANACOR**, **MARÍA**,
**LLOSETA**, **LLUBÍ**, **LLUCALCARI**, **LLORITO** plus
**LLANO DE LA VILLA** (Ibiza). 12 Balearic entries total.

For **Tomo X** the IA scan is genuinely partial (~125 pages of body,
no Z-words) — only YEBRA showed up as a candidate, correctly purged
as peninsular. Balearic content in that scan is nil.

With this, **all 11 tomos are processable** through the pipeline. No
workaround backlog remains.

## Differences vs. madoz

The strategy is the same five-phase shape as
[`../madoz`](../madoz/README.md), but several details differ
materially:

| | Madoz | Miñano |
|---|---|---|
| Years | 1845–1850 | 1826–1829 |
| Volumes | 16 | 11 (10 alphabetical + 1 Suplemento) |
| IA identifiers | `diccionariogeogr<NN>mado` (regular) | heterogeneous — different libraries, no shared prefix |
| Title separator in entries | colon (`ARTA: V. de la isla…`) | comma (`BINISALEM, V. R. de Esp.…`), often dropped entirely |
| Type abbreviations | `V.`, `cas.`, `l.`, `alq.`, `predio`, … | `V.`, `L.`, `Ald.`, `Cas.`, `Castillo`, `Jurisd.`, `Herm.`, … |
| Realengo/señorial flag | rarely stamped | always stamped (`V. R.` realenga, `V. S.` señorial, `L. Ab.` abadengo, `L. Ord.` de órdenes, `L. Ecl.` eclesiástico) |
| Statistics tables | per-municipality multi-column grids (chocr-mangled) | inline prose figures (`A. P., 76 vec, 318 hab.`) — easier to extract |
| Pre-Loi-Salic style | "alma" (= soul) and "vecino" (= household) | same, plus *contribuye con* references that point to the dependency municipality |
| Front matter | one volume each | each tomo carries its own dedication, prólogo, abreviaturas page |
| Cross-volume mega-articles | PALMA, MAHON, IBIZA, ALCUDIA, … | likely thinner (Miñano's articles are shorter on average); won't know until M-tomo and P-tomo are indexed |

Crucially, Miñano's **chocr has the same paragraph-per-entry structure
as Madoz's** — both are Google Books ABBYY output, so the indexing
strategy (one `<p class="ocr_par">` ≈ one entry) ports cleanly.

## Pipeline

### Phase 1 — Index from chOCR (deterministic)

For each tomo, fetch from Internet Archive:

```
data/chocr/tomo<vol>.html.gz          # compressed hOCR (~27 MB)
data/page_numbers/tomo<vol>.json      # leaf → printed-page map
data/txt_djvu/tomo<vol>.txt           # plain text (for ad-hoc grep)
```

`scripts/index_volume.py` then parses the hOCR **by paragraph**.
Each Miñano entry is essentially one paragraph, so paragraph
boundaries give free entry segmentation. A pair of regexes (STRICT
with a comma separator, LOOSE without a separator but requiring a
canonical Miñano body marker) extract the title; a double-signal
Balearic filter (canonical marker near a place name, or ≥ 2 distinct
mentions of Balearic places) gates inclusion.

Output → `data/index/tomo<vol>.jsonl`. One row per entry:

```json
{"vol": "02", "leaf": 137, "page_printed": "123",
 "title": "BINISALEM",
 "context": "V. R. de Esp., en la isla de Mallorca y su obisp…"}
```

### Phase 3 — Claude extraction over chocr (canonical path)

`scripts/extract_text.py` walks every Balearic leaf in
`data/index/tomo<vol>.jsonl` and asks Claude Sonnet 4.6 to:

- Locate the target entries on that leaf in the chocr text.
- Clean OCR glue (`islade Mallorca` → `isla de Mallorca`,
  `V.S.deEsp.` → `V. S. de Esp.`) and digit confusions
  (`rjg vec.` → `39 vec.`, `^18 hab.` → `118 hab.`).
- Preserve Miñano's abbreviation style verbatim (`prov.`,
  `obisp.`, `A. O.` / `A. P.`, `vec.`, `hab.`,
  `Contr. con Palma`, `V.` for *véase*).
- Preserve Miñano's authentic hispanicised spellings (`CAIMARY`,
  `BÜÑOLA`, `BINARAÜS`, `CALVIA`) — do **not** modernise to current
  Catalan toponyms.
- Emit a structured JSON ``{title, place_type, island,
  seigneurial_regime, mayor_type, municipality, description, stats,
  cross_references, confidence}``. The two Miñano-specific fields
  (compared to madoz) are ``seigneurial_regime`` (Realengo /
  Señorial / Abadengo / de Órdenes / Eclesiástico) and
  ``mayor_type`` (Alcalde Ordinario / Pedáneo / Sin alcalde) — both
  are stamped on every civil-jurisdiction entry. ``judicial_district``
  is dropped because the partido judicial reform is from 1834.

One JSON file per leaf goes to `data/text/page_<vol>_<leaf>.json`.

Mega-articles (MALLORCA, MENORCA, MAHON, PALMA, IBIZA, IVIZA,
CIUDADELA, ALCUDIA, MANACOR, BALEARES) trigger a 4-leaf chocr window
so multi-leaf bodies stay intact; everything else uses the default
2-leaf window.

Validated on all 10 leaves of Tomo II: 13/13 Balearic entries
extracted, 0 low-confidence, ~$0.25 total.

### Phase 4 — Load into DuckDB

`scripts/load_text.py` reads every ``data/text/page_<vol>_<leaf>.json``
and inserts one row per entry into ``db/minano.duckdb``'s
``text_entries`` table (schema in ``db/schema.sql``). Each run
fully replaces the table — the JSON files are the source-of-truth,
the DB is a derived index for ad-hoc SQL.

Schema highlights vs. madoz:

- `judicial_district` is *not* present (anachronistic — the partido
  judicial reform is from 1834, post-Miñano).
- `seigneurial_regime` and `mayor_type` are present (Miñano always
  stamps them; Madoz drops them).
- No `madoz_entries` table — there is no third-party WordPress
  mirror of Miñano to scrape from.

### Phase 5 — Web export + static site

`scripts/export_web_data.py` flattens `text_entries` into a single
`web/data.json` (~11 KB for Tomo II's 13 entries) consumed directly
by the static site under `web/`:

- `web/index.html` — three tabs (Inici / Explorar / Notes). No
  Estadístiques or Demografia tabs yet — only 13 entries on one tomo;
  add them when there's more to chart.
- `web/app.js` — vanilla JS, no framework, no DuckDB-WASM. Filters,
  sortable table, expandable rows showing the full description,
  per-row IA-facsimile link, CSV export.
- `web/style.css` — slim port (~12 KB) of madoz's 1860-nomenclator
  palette.

Serve locally with `python -m http.server -d web 8000`.

### Phase 2 — Cross-reference: not yet implemented

No diccionariomadoz.com-equivalent for Miñano exists. If we want
cross-reference, it'll be against the BNE / BDH digital facsimiles
directly (page-image links).

## Known issues

Surfaced by the Phase 1 calibration on Tomo II:

- ~~**Peninsular Cabrera homonyms slip through.**~~ Solved by
  `scripts/purge_non_balearic.py`: the script re-loads each entry's
  full chocr paragraph and re-tests for an explicit Balearic anchor
  (``(isla|prov.|obisp.) [...] (Mallorca|Menorca|Ibiza|Iviza|
  Formentera|Baleares)``) in the first ~140 chars of body, with
  OCR-fuzzy variants of the place names. All 7 peninsular Cabrera
  / Vizcaya / Salamanca homonyms in Tomo II are dropped, no true
  positive is lost. The script is idempotent and dry-run by default —
  pass `--apply` to overwrite the JSONL.

- ~~**OCR noise breaks some titles.**~~ Partially solved: the
  indexer now tolerates ``^_`` mid-title (with post-strip), which
  recovers ``CABRER^A (Isla de)`` automatically. Other classes of
  OCR mangling (digit/letter confusion at word-end, accent
  drops, paren mangles, …) are handled case-by-case via
  `scripts/fix_ocr_titles.py`. Document each fix's source-of-truth
  inline in `FIXES`.

- **Title splits inside words.** OCR sometimes inserts a space mid-
  word in the title: ``BEL VER`` (should be ``BELVER``), ``BUGEU``
  (should be ``BUGER``, R→U misread). ``BEL VER`` and ``BUGEU`` are
  fixed in the FIXES table of `fix_ocr_titles.py`. ``CAP DE PERA``
  is *not* fixed — Miñano printed the Castle as three words
  (matching the Mallorquí placename ``Cap de Pera``), so this is
  not OCR but the source's own typography.

- **Continuation paragraphs lose their head.** When an entry spans
  multiple paragraphs (e.g. the second column of CAMPOS), the head
  contains no caps title, so the paragraph is rejected even though it
  belongs to a Balearic article. The Madoz workaround (read a ±4-leaf
  window for known mega-articles in `recover_municipality_articles.py`)
  will work here too once Phase 3 is in place.

- **Volume coverage is incomplete.** Only Tomos II (the proof of
  concept) and XI (the Suplemento) are fetched. The other 9 tomos'
  IA identifiers still need to be resolved (different libraries, no
  shared prefix, see TODO in `scripts/fetch_volume.py`).

## Layout

```
data/
  chocr/             # hOCR per tomo (gitignored, ~27 MB each)
  page_numbers/      # leaf→page maps per tomo (gitignored)
  txt_djvu/          # plain OCR text per tomo (gitignored)
  index/             # per-tomo JSONL indexes (versioned)
  minano/            # placeholder for any future curated-mirror scrape
  reports/           # audit HTML reports (gitignored)
db/                  # placeholder for a DuckDB once Phase 4 ships
db/
  schema.sql              # DuckDB schema for text_entries (versioned)
  minano.duckdb           # built DB (gitignored, regenerable from data/text/)
scripts/
  fetch_volume.py              # download chocr + page_numbers + djvu (Tomos I-IV, VI-IX, XI)
  derive_chocr_from_abbyy.py   # download _abbyy.gz → abbyy-to-hocr → chocr (Tomos V, X)
  index_volume.py              # parse chocr → Balearic-filtered JSONL (recall-heavy)
  purge_non_balearic.py   # drop peninsular homonyms (idempotent; --apply to write)
  fix_ocr_titles.py       # hand-curated FIXES list for OCR-mangled titles
  extract_text.py         # Phase 3 Claude extraction → data/text/page_<vol>_<leaf>.json
  load_text.py            # flatten data/text/ JSONs into db/minano.duckdb
  export_web_data.py      # text_entries → web/data.json for the static site
  probe_paragraphs.py     # ad-hoc calibration utility (paragraph-structure probe)
web/
  index.html              # 3 tabs: Inici / Explorar / Notes
  app.js                  # vanilla JS, no framework
  style.css               # slim 1860-nomenclator palette
  data.json               # generated by export_web_data.py
web/                 # placeholder for the eventual static site
```

## Usage

```bash
# One-time setup (matches madoz's environment)
uv venv && uv pip install -e .

# Phase 1 on Tomo II (tomos served as chocr by IA)
python scripts/fetch_volume.py 02
python scripts/index_volume.py 02
python scripts/purge_non_balearic.py 02 --apply   # drop peninsular homonyms
python scripts/fix_ocr_titles.py 02 --apply       # hand-curated OCR fixes
head data/index/tomo02.jsonl

# Phase 1 on Tomo V (chocr derived locally from ABBYY raw)
pip install archive-hocr-tools scikit-learn viterbi-trellis roman
python scripts/derive_chocr_from_abbyy.py 05      # → data/chocr/tomo05.html.gz
python scripts/index_volume.py 05
python scripts/purge_non_balearic.py 05 --apply

# Phase 3 on Tomo II — needs ANTHROPIC_API_KEY in .env
python scripts/extract_text.py --page 02 137      # one leaf (smoke test)
python scripts/extract_text.py --sample 02        # 3-leaf curated sample
python scripts/extract_text.py --all 02           # every leaf in the index
ls data/text/page_02_*.json

# Phases 4 & 5 — build DB and the static web payload
python scripts/load_text.py                       # data/text/ → db/minano.duckdb
python scripts/export_web_data.py                 # db → web/data.json

# Serve the site locally
python -m http.server -d web 8000
open http://localhost:8000
```

To add a new tomo, look up its IA identifier (e.g. via
``archive.org/details/<id>`` and confirm the title page says the
right tomo number), then add it to `VOL_TO_IDENTIFIER` in
`scripts/fetch_volume.py`.

## Language convention

As in madoz: code, scripts, commit messages and this README are in
English so the project stays navigable. The eventual public-facing
website and any content-targeted notes will be in Catalan, mirroring
[`../madoz/web/`](../madoz/web/).

## License

Code is licensed under **AGPL-3.0-or-later** (see `LICENSE`). If you
run a modified version as a network service, you must offer the
source of your modifications to its users.

Underlying data carries the licence of its origin: the Miñano
facsimile (Internet Archive scans of an 1826–1829 work) is public
domain.
