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
exploration. Sister projects of the same family are
[`../madoz`](../madoz), `../Nomenclator`, `../floridablanca` and
`../nomenclator_1860`; each is independent and self-contained.

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
   Illes Balears: 55 531 modern toponyms). The match is fuzzy and
   normalises Miñano's hispanicised orthography (`Iviza` → *Eivissa*,
   `Bañalbufar` → *Banyalbufar*, etc.). Articles that cannot be matched
   directly fall back to their parent municipality, and articles with
   no resolvable parent fall back to the centroid of the corresponding
   island. The geographic data download is fully reproducible from the
   IDEIB ArcGIS REST endpoint.

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
