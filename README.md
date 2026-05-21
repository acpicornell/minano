# Miñano · Balearic subset

Digital edition of the **Balearic Islands articles** of Sebastián
Miñano y Bedoya's *Diccionario geográfico-estadístico de España y
Portugal* (Madrid, 1826–1829, 11 vols.).

The original work is the first modern geographical-statistical
dictionary of the Iberian Peninsula and the immediate predecessor of
Pascual Madoz's *Diccionario* (1845–1850). It describes a pre-liberal
Spain that still records the seigneurial regime of every locality
(*realengo*, *señorial*, *abadengo*, *de órdenes*, *eclesiástico*),
two decades before Mendizábal's confiscations.

This repository extracts every article relating to Mallorca, Menorca,
Eivissa, Formentera and Cabrera, structures the data into a relational
schema, and publishes a static website for consultation and
exploration.

## Coverage

| Indicator | Value |
|---|---|
| Volumes processed | 11 / 11 (1826–1829) |
| Balearic articles extracted | 182 |
| Articles with geographic coordinates | 99.5 % |
| Public website | [`web/`](web/index.html) (static, vanilla JS) |
| License | AGPL-3.0-or-later (code); original text in the public domain |

The only documented gap is Tomo X (VIL–VIZ): the available Internet
Archive scan is partial and does not include any Balearic entry.

## Pipeline

The extraction is a four-stage pipeline. All stages are deterministic
except the Anthropic-model call in stage 2; the model output is
checked into the repository as JSON, so the database and the website
can be rebuilt without re-spending tokens.

1. **OCR ingestion.** For each volume, the chOCR (character-level
   hOCR with bounding boxes) is fetched from Internet Archive. Tomos V
   and X are not served as chOCR by Internet Archive; they are
   regenerated locally from the ABBYY FineReader XML using the same
   open-source toolchain that Internet Archive itself runs. The result
   is bit-for-bit equivalent to what IA serves for the other volumes.

2. **Article identification and extraction.** A fuzzy regex indexer
   scans the chOCR paragraph by paragraph and selects those that
   contain a Balearic anchor (place name plus jurisdictional marker).
   A second, OCR-tolerant pass recovers articles that the first regex
   missed because of severe OCR damage (e.g. `POLUSNZA` for *Pollença*,
   `ALClülA` for *Alcúdia*, `CABRER^A` for *Cabrera*). Each candidate
   leaf is then sent to an Anthropic language model (current run:
   Claude Opus 4.7), which reads the chOCR text and emits a structured
   JSON object per article with the following fields:

   ```
   title · place_type · island · seigneurial_regime · mayor_type
   municipality · description · stats · cross_references · confidence
   ```

   The extracted JSONs live under `data/text/page_<vol>_<leaf>.json`
   and are the canonical source of truth for the rest of the pipeline.

3. **Geocoding.** Each extracted title is matched against the
   **Nomenclàtor Geogràfic de les Illes Balears** (NGIB, Govern de les
   Illes Balears: 55 531 modern toponyms). The geographic data
   download is fully reproducible from the IDEIB ArcGIS REST endpoint.
   The matcher normalises Miñano's hispanicised orthography
   (`Iviza` → *Eivissa*, `Bañalbufar` → *Banyalbufar*, hyphens and
   en/em dashes folded to spaces so `ALCARIA-ROJA` aligns with
   `ALQUERIA ROJA`) and curates a short table of 19th-century
   Castilian forms whose modern equivalents NGIB carries under a
   different lemma (e.g. *Alcaria* → *Alqueria*).

   Resolving toponyms against NGIB faithfully proved more involved
   than a single fuzzy lookup. The matcher therefore relies on six
   complementary safeguards, each addressing a distinct failure mode
   observed in NGIB's structure or in Miñano's typography:

   - **Authoritative-type priority.** Many Balearic toponyms recur
     in NGIB under several `local_type` values (e.g. `sa Pobla`
     exists both as a *Municipi* at the northern village and as a
     *Finca, possessió* at a Llucmajor farm). The gazetteer builder
     sorts candidates by an explicit priority list — `Municipi` >
     `Capital de municipi` > `Vila` > `Entitat de Població` >
     `Llogaret` > … > `Finca, possessió` — so the most authoritative
     row wins the `(normalised, island)` deduplication.

   - **Complete settlement-type coverage.** NGIB classifies many
     small but real settlements (Fornells of Menorca, es Capdellà,
     Llucalcari, several Eivissan parish villages) under the type
     `Altre nucli de població, llogaret`, and the four main islands
     and their islets under `Illa gran` and `Illa mitjana`. All
     these are now included in the gazetteer; their previous
     omission was causing matches to fall through to homonyms on
     other islands.

   - **Strict same-island matching.** When an entry declares its
     island, the candidate pool is restricted to that island.
     Cross-island fallback only applies when no island is declared
     (e.g. Balearic-wide articles). Without this constraint Eivissa's
     `es Fornells` was wrongly matched against Menorca's *Fornells*,
     Mallorcan possessions against Menorcan homonyms, and so on.

   - **Length-disparity guard.** Levenshtein-based fuzzy scorers
     (such as `WRatio`) award high marks when one string is a
     substring of the other; without correction, `ROJA` scored 90
     against `ALCARIA ROJA`. Candidates shorter than 60 % of the
     title's normalised length are discarded before scoring.

   - **Municipality tiebreaker.** When the article declares a parent
     municipality (`Sit. al N. O. de Palma…`), homonyms in that
     municipality are preferred over equally-scoring candidates
     elsewhere on the same island.

   - **Curated overrides and ambiguous-homonym signalling.** A
     small table of explicit `(island, title) → (lon, lat)` entries
     resolves cases NGIB cannot disambiguate algorithmically because
     the title appears under several settlements with different
     types (e.g. *la Vileta* of Palma over the four other Mallorcan
     *sa Vileta* hamlets). A second table marks titles whose Miñano
     description is too thin to permit any disambiguation — the
     one-line *Coto Redondo* notices that name no village, no
     distance and no jurisdiction — and routes them to the island
     centroid with a distinct fallback label so they are visually
     distinguishable from centroid-fallback cases of unmatched
     toponyms.

   Articles that cannot be matched directly fall back to their
   parent municipality, and articles with no resolvable parent fall
   back to the centroid of the corresponding island. The aggregate
   match rate is 99.5 %; every matched entry is independently
   verified to land within the bounding box of its declared island
   and within 1 km of the canonical NGIB coordinates of its matched
   toponym.

4. **Publication.** The per-article JSONs are loaded into a DuckDB
   database and exported as a single `web/data.json` consumed by the
   static site. The site uses no framework: HTML, CSS and one
   JavaScript file. Leaflet is loaded lazily from CDN on the *Mapa*
   tab.

## Website

The static site under `web/` presents the corpus through five tabs:

- **Inici** — orientation, statistics by island, source-volume table.
- **Explorar** — filtered table of every article, with full text on
  expansion and a direct link to the corresponding page of the
  Internet Archive facsimile.
- **Mapa** — geographical distribution on a Leaflet map; circle size
  proportional to declared *vecinos*, colour by island.
- **Estadístiques** — nine visualisations covering demography
  (habitants and vecinos by entry, household size), fiscality
  (*riqueza líquida* in libras mallorquinas), administrative typology,
  per-volume distribution, and a sunburst diagram cross-tabulating
  island, seigneurial regime and place type.
- **Notes** — scholarly notes on Miñano's biography, the method by
  which the *Diccionario* was elaborated (correspondence with parish
  priests, after the model of the Felipe II *Relaciones Topográficas*),
  the role of fra Lluís de Vilafranca as the Balearic correspondent,
  the *Corrección fraterna* polemic with Fermín Caballero, the
  transition to Madoz, and the abbreviations used in the original work.

The website language is Catalan. Code, scripts and this README are in
English.

## Sources

The eleven volumes are scattered across multiple Internet Archive
deposits — different libraries, no shared identifier prefix. The
canonical source used for each volume is listed in the *Fonts*
section of `web/index.html` (Tom I to XI, with the digitising
institution and the IA identifier of each scan).

## Running locally

```bash
uv venv && uv pip install -e .

# Reproduce the full extraction (writes data/text/, db/minano.duckdb,
# web/data.json). Requires ANTHROPIC_API_KEY for stage 2.
python scripts/fetch_volume.py <vol>          # OCR ingestion (one volume)
python scripts/derive_chocr_from_abbyy.py 05  # for Tomos V and X only
python scripts/index_volume.py <vol>
python scripts/extract_text.py --all <vol>    # stage 2 (LLM)
python scripts/fetch_ngib.py                  # NGIB gazetteer download
python scripts/build_gazetteer.py
python scripts/enrich_coords.py               # stage 3 (geocoding)
python scripts/load_text.py                   # stage 4 (DB)
python scripts/export_web_data.py             # stage 4 (web/data.json)

# Serve the static site
python -m http.server -d web 8000
```

The pipeline is idempotent: re-running any stage overwrites its
outputs in place, with the data under `data/text/` as the single
source of truth.

## License

Code: AGPL-3.0-or-later (see `LICENSE`). Running a modified version
as a network service obliges the operator to make the modifications
available to its users.

Original text (1826–1829) and the Internet Archive facsimiles derived
from public-domain editions are themselves in the public domain.
