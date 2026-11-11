# Corpus and sources

## The source

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
| Balearic articles extracted | 211 |
| Articles with geographic coordinates | 210 / 211 (99.5 %), 10 of them approximate |
| Public website | [`web/`](../web/index.html) (static, vanilla JS) |
| License | AGPL-3.0-or-later (code); original text in the public domain |

The only documented gap is Tomo X (VIL–VIZ): the available Internet
Archive scan is partial and does not include any Balearic entry.

## Sources

The eleven volumes are scattered across multiple Internet Archive
deposits — different libraries, no shared identifier prefix. The
canonical source used for each volume is listed in the *Fonts*
section of `web/index.html` (Tom I to XI, with the digitising
institution and the IA identifier of each scan).

