# Miñano · Balearic subset

[![Deploy](https://github.com/acpicornell/minano/actions/workflows/deploy.yml/badge.svg)](https://github.com/acpicornell/minano/actions/workflows/deploy.yml)

Digital edition of the **Balearic Islands articles** of Sebastián
Miñano y Bedoya's *Diccionario geográfico-estadístico de España y
Portugal* (Madrid, 1826–1829, 11 vols.). This repository extracts every
article relating to Mallorca, Menorca, Eivissa, Formentera and Cabrera,
structures it into a relational schema and publishes a static website.

Live at <https://minano.corpusbalear.org>. Part of
[Corpus Balear](https://corpusbalear.org).

## What's in it

- 11 of 11 volumes processed (1826–1829); the only documented gap is
  Tomo X (VIL–VIZ), whose Internet Archive scan holds no Balearic entry.
- 182 Balearic articles extracted, 99.5 % of them with geographic
  coordinates.
- A static site in Catalan (`web/`): explorable table, map, statistics
  and scholarly notes.

## How it was made

The character-level OCR of each volume is fetched from Internet Archive,
and a fuzzy indexer plus three recovery audits find the Balearic
articles. An Anthropic model turns each article into a structured JSON
record, which is checked into the repository as the source of truth.
Titles are geocoded against the *Nomenclàtor Geogràfic de les Illes
Balears* (NGIB), loaded into DuckDB and exported as `web/data.json`.

## Run locally

```bash
uv venv && uv pip install -e .
python scripts/load_text.py          # data/text/ -> db/minano.duckdb
python scripts/export_web_data.py    # -> web/data.json
python -m http.server -d web 8000
```

`web/data.json` is committed, so serving `web/` alone is enough. The full
extraction is in [docs/PIPELINE.md](docs/PIPELINE.md).

## Documentation

- [docs/CORPUS.md](docs/CORPUS.md) — the source work, coverage figures
  and where each volume's scan comes from.
- [docs/PIPELINE.md](docs/PIPELINE.md) — the four stages (OCR ingestion,
  article identification and recovery audits, geocoding, publication)
  and the commands to reproduce them.
- [docs/WEBSITE.md](docs/WEBSITE.md) — the five tabs of the static site.

## License

Code: AGPL-3.0-or-later (see `LICENSE`). Running a modified version
as a network service obliges the operator to make the modifications
available to its users.

Original text (1826–1829) and the Internet Archive facsimiles derived
from public-domain editions are themselves in the public domain.

## How to cite

As given in the site footer:

> Picornell Company, A. C. *Diccionari de Miñano* (1826), edició digital.
> Corpus Balear · minano.corpusbalear.org
