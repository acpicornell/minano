"""Index a Miñano volume by exploiting hOCR paragraph structure.

Phase 1 of the pipeline: for each Balearic entry in a Miñano tomo,
record its exact location in the original edition — volume, leaf,
printed page — so phase 3 (Claude extraction) can fetch the correct
chocr window directly.

Approach (parallel to ../madoz/scripts/index_volume.py, with the
following Miñano-specific calibrations):

1. Stream the chocr and emit one **paragraph** (`<p class="ocr_par">`)
   per leaf at a time. Empirically (probe_paragraphs.py) one paragraph
   ≈ one Miñano entry — same as Madoz.

2. Match the entry head. Miñano's canonical form is::

       TITLE , Type. de Esp., …
       BINARAÜS , Aid. R. de Esp., en la isla de Mallorca; …
       BELVER , Castillo de Esp., en la isla de Mallorca. Sit. …
       BENUZA , L. S. de Esp., prov. y partido de León, …
       BIERZO , Provincia pequeña ó mas bien part. de Esp., …

   The separator is a **comma** (not Madoz's `:`); sometimes the OCR
   drops it (``BUÑOL V. S. de España``), so a loose fallback accepts
   any whitespace as separator as long as the body begins with a
   canonical Miñano type marker.

3. Verify Balearic context with the double-signal filter ported from
   Madoz: a canonical marker (isla/prov./dióc./…) near a Balearic
   place name, or ≥ 2 distinct Balearic mentions in the body. The
   place-name list (Mallorca/Menorca/Ibiza/Iviza/Formentera/Cabrera/
   Baleares + OCR mangles) is unchanged — Miñano predates Madoz but
   uses the same names with the same OCR confusions.

4. Resolve ``leafNum → printed page`` via ``page_numbers.json``.

5. Emit JSON Lines to ``data/index/tomo<vol>.jsonl``.

Run: ``python scripts/index_volume.py <vol>``  (e.g. ``02``)
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"
CHOCR_DIR = DATA / "chocr"
PAGENUM_DIR = DATA / "page_numbers"
OUT_DIR = DATA / "index"


# ---------- Entry-head regex ----------------------------------------------

# Title-internal OCR noise chars we tolerate INSIDE the caps run. Two
# distinct categories:
#
# 1) Punctuation/symbol noise (``^_``) — stripped post-match
#    (``CABRER^A (Isla de)`` → ``CABRERA (Isla de)``).
#
# 2) Lowercase-OCR'd uppercase letters (``hnu``) — three lowercase
#    glyphs that BSB/Google OCR routinely produces in place of uppercase
#    ``N/N/U``:
#      - ``h`` ↔ ``N`` (``VILAFRAhCA`` → ``VILAFRANCA``)
#      - ``n`` ↔ ``N`` (sometimes the OCR keeps the case wrong)
#      - ``u`` ↔ ``U``
#    These are NOT stripped — they are uppercased so the title reads
#    correctly. ``VILAFRAhCA``.upper() → ``VILAFRAHCA`` (so we still
#    need a manual FIXES entry for the ``H``→``N`` step, but at least
#    the entry is captured).
#
# Kept TINY on purpose — any wider and we start swallowing real text.
TITLE_NOISE_CHARS = r'\^_'
TITLE_LOWER_TOLERATED = r'hnu'
TITLE_NOISE_RE = re.compile(f'[{TITLE_NOISE_CHARS}]+')


def _strip_title_noise(title: str) -> str:
    """Remove tolerated OCR noise from a captured title, then uppercase
    the tolerated lowercase-OCR letters."""
    return TITLE_NOISE_RE.sub('', title).translate(
        {ord(c): ord(c.upper()) for c in TITLE_LOWER_TOLERATED}
    )


# STRICT: a comma (with optional surrounding whitespace) between the
# title and the body. Matches the canonical Miñano typesetting.
PAT_ENTRY_STRICT = re.compile(
    r'^[\s\'\"~`«»_\.\-\(\)\[\]\{\}t0\d]{0,6}'   # leading OCR junk
    r'(?P<title>'
        r'[A-ZÑÁÉÍÓÚÜ][A-ZÑÁÉÍÓÚÜ0-9' + TITLE_NOISE_CHARS + TITLE_LOWER_TOLERATED + r']{1,}'   # initial caps run
        r'(?:\s+(?:[óòo]\s+)?[A-ZÑÁÉÍÓÚÜ' + TITLE_NOISE_CHARS + TITLE_LOWER_TOLERATED + r']+(?:[\-\'][A-ZÑÁÉÍÓÚÜ]+)*)*'
        r'(?:\s*\([A-Za-zñáéíóúÑÁÉÍÓÚÜ0-9\s\.,\-\']{1,30}\))?'
    r')'
    r'\s*,\s*'                                    # canonical separator
    r'(?P<body>.+)',
    re.DOTALL,
)

# LOOSE: no separator. Used when STRICT fails; requires the body to
# start with a Miñano body-type marker (see BODY_MARKER below).
PAT_ENTRY_LOOSE = re.compile(
    r'^[\s\'\"~`«»_\.\-\(\)\[\]\{\}t0\d]{0,6}'
    r'(?P<title>'
        r'[A-ZÑÁÉÍÓÚÜ][A-ZÑÁÉÍÓÚÜ0-9' + TITLE_NOISE_CHARS + r']{1,}'
        r'(?:\s+(?:[óòo]\s+)?[A-ZÑÁÉÍÓÚÜ' + TITLE_NOISE_CHARS + r']+(?:[\-\'][A-ZÑÁÉÍÓÚÜ]+)*)*'
        r'(?:\s*\([A-Za-zñáéíóúÑÁÉÍÓÚÜ0-9\s\.,\-\']{1,30}\))?'
    r')'
    r'[\s\.•:;\'\"]{1,4}'
    r'(?P<body>.+)',
    re.DOTALL,
)

# Miñano body markers — the first 1-3 tokens of an entry body. The
# canonical sequence is "<TYPE>. <CLASS>. de Esp[aña]" where TYPE is a
# single-letter abbreviation (V., L., C., Ald., …) and CLASS is one of
# R., S., Ab., Ord., Ecl. (Realenga, Señorial, Abadengo, de Órdenes,
# Eclesiástico). The OCR often mangles "Ald." → "Aid." and "Desp." →
# "Dcsp.", which we tolerate.
BODY_MARKER = re.compile(
    r'^\(?\s*(?:'
    # Full words — terminator must be a non-letter.
    r'(?:provincia|provincias|prov\b|partido|jurisdicci[óo]n|jurisd|'
    r'castillo|fortaleza|sierra|monte|monta[ñn]a|valle|cabo|cala|'
    r'punta|playa|bah[ií]a|puerto|isla|isleta|islote|isleo|r[ií]o|'
    r'riachuelo|arroyo|fuente|laguna|lago|despoblado|aldea|aldehuela|'
    r'lugar|villa|caser[ií]o|cortijo|cortijada|granja|barrio|barriada|'
    r'pago|coto|parroquia|feligres[ií]a|barrio|hermandad|herm|territorio|'
    r'cuart[óo]n|distrito|departamento|ferrer[ií]a|hacienda|santuario|'
    r'ermita|capilla|santuario|atalaya|mirador|pico|baron[ií]a|condado|'
    r'mayorazgo|coto|despobl|antigua|antiguo|pueblo|poblaci[óo]n'
    r')(?=[^A-Za-zñáéíóúÑÁÉÍÓÚÜ])'
    r'|'
    # Single-letter type abbreviations + dot. Miñano's most common.
    # V.=Villa, L.=Lugar, Ald.=Aldea, Aid.=Aldea (OCR), Cas.=Caserío,
    # C.=Ciudad, Cot.=Coto, Desp.=Despoblado, Dcsp.=Despoblado (OCR),
    # Felig.=Feligresía, Parr.=Parroquia, Herm.=Hermandad,
    # Jurisd.=Jurisdicción.
    r'(?:V|L|C|Ald|Aid|Cas|Cot|Desp|Dcsp|Felig|Parr|Parroq|Herm|Jurisd|'
    r'Ferr|Mont|Mont[eñ]a|Cab|Cabe|Cap|Brg|Cor|Cdo|Bn|Vd|Vill|R|S|Pred)\.'
    r')',
    re.IGNORECASE,
)


# ---------- Balearic filter (unchanged from madoz/index_volume.py) -------

# Canonical: Miñano-style geographic marker near a Balearic name.
#
# OCR-tolerant additions (observed empirically when indexing Tomo IX):
#   - "Illa" — Catalan/Italian spelling Miñano occasionally uses
#     (e.g. ``VILAFRANCA , L. R. de España en la Illa de Mallorca``)
#   - "pror." — OCR mangle of "prov." (v→r), common in BSB scans
#     (e.g. ``VILLAC ARLOS, V. R. d« Esp., pror. de Menorca``)
PAT_BALEAR_CANON = re.compile(
    r'\b(?:isla|Illa|isl\.|prov\.|pror\.|provincia|adm\.|di[óo]c\.|partido|cala|punta|cabo|sierra|'
    r'valle|bahia|bahía|monte|playa|puerto|tercio|distr\.|distrito|'
    r'mar[ií]t(?:imo)?\.?|aud\.|c\. g\.|jurisd\.|herm\.)\.?'
    r'.{0,40}?'
    r'(?:Mallorca|Mallorea|Menorca|Menorea|Ibiza|Iviza|Formentera|Cabrera|'
    r'Baleares|Raleares|Paleares|Balea\b|'
    r'Mall\.|Men\.|Form\.|Cabr\.)',
    re.IGNORECASE | re.DOTALL,
)

PAT_BALEAR_ANY = re.compile(
    r'\b(?:'
        r'Mallorca|Mallorea|Menorca|Menorea|Ibiza|Iviza|Formentera|Cabrera|'
        r'Baleares|Raleares|Paleares|Balea|'
        r'Mall\.|Men\.|Form\.|Cabr\.|'
        r'M[aá][li1!|tj]{2}[oa0][rnti][ceoa][aá]|'
        r'M[eé][ni1!|m]{1,2}[oa0][rnti][ceoa][aá]|'
        r'[Ili1!|jJ][bdh][i1!|jl][zsxv][a4o]|'
        r'[Ili1!|jJ]v[i1!|jl][zsxv][a4]|'
        r'F[oa0]rm[eé][nuim]t[ecoa][rnti][a4o]|'
        r'C[a4]br[ecoa][rnti][a4]|'
        r'[BRPDIS][a4]l[ecoa]{1,2}r[ecoa]s|'
        r'H[ua]l[ecoa]{1,2}r[ecoa]s|'
        r'[BRPDIS][a4]l[ecoa][a4]'
    r')\b',
    re.IGNORECASE,
)


def passes_balear(body_search: str) -> bool:
    """Double-signal Balearic filter.

    Accept if either (a) a Miñano geographic marker sits near a Balearic
    name, or (b) the body contains ≥ 2 distinct Balearic mentions.
    Same shape as madoz/index_volume.py:passes_balear — the rationale
    (1 fuzzy can fire on Sierra Cabrera in Almería, but a real Balearic
    article has at least two coreferent mentions) carries over.
    """
    if PAT_BALEAR_CANON.search(body_search):
        return True
    hits = {m.group(0).lower() for m in PAT_BALEAR_ANY.finditer(body_search)}
    return len(hits) >= 2


# ---------- Title rejection -----------------------------------------------

TITLE_BLACKLIST = {
    "DICCIONARIO", "GEOGRAFICO", "GEOGRÁFICO", "ESTADISTICO", "ESTADÍSTICO",
    "ESPAÑA", "PORTUGAL", "MADRID", "TOMO", "ADVERTENCIA", "PROLOGO",
    "PRÓLOGO", "INTRODUCCION", "INTRODUCCIÓN", "INDICE", "ÍNDICE",
    "MAPAS", "PESOS", "MEDIDAS", "ABREVIATURAS", "FIN", "SUPLEMENTO",
}

HEADER_TOKENS = re.compile(
    r'^(?:DICCIONARIO|GEOGRÁFICO|ESTADÍSTICO|ESPAÑA|PORTUGAL|'
    r'TOMO|FIN|ADVERTENCIA)\b',
    re.IGNORECASE,
)


# ---------- chOCR streaming ------------------------------------------------

PAGE_PAT = re.compile(r'class="ocr_page" id="page_(\d+)"')
PAR_OPEN_PAT = re.compile(r'<p class="ocr_par"')
CHAR_PAT = re.compile(r'<span class="ocrx_cinfo"[^>]*>([^<])</span>')


def iter_paragraphs(chocr_path: Path):
    """Yield (leaf:int, paragraph_text:str) for each paragraph.

    Streams the file without loading it all into memory. Each hOCR tag
    sits on its own line in the IA chocr file.
    """
    opener = gzip.open if chocr_path.suffix == ".gz" else open
    current_leaf = None
    buf: list[str] = []
    in_par = False
    with opener(chocr_path, "rt", encoding="utf-8") as f:
        for line in f:
            m_page = PAGE_PAT.search(line)
            if m_page:
                if buf:
                    yield current_leaf, "".join(buf)
                    buf = []
                current_leaf = int(m_page.group(1))
                in_par = False
                continue
            if PAR_OPEN_PAT.search(line):
                if buf:
                    yield current_leaf, "".join(buf)
                    buf = []
                in_par = True
                continue
            if "</p>" in line:
                if buf:
                    yield current_leaf, "".join(buf)
                    buf = []
                in_par = False
                continue
            if in_par:
                for cm in CHAR_PAT.finditer(line):
                    buf.append(cm.group(1))
    if buf:
        yield current_leaf, "".join(buf)


# ---------- Indexing ------------------------------------------------------

def index_volume(vol: str) -> list[dict]:
    chocr_path = CHOCR_DIR / f"tomo{vol}.html.gz"
    pn_path = PAGENUM_DIR / f"tomo{vol}.json"
    if not chocr_path.exists():
        sys.exit(f"Missing {chocr_path}. Run first: python scripts/fetch_volume.py {vol}")
    if not pn_path.exists():
        sys.exit(f"Missing {pn_path}. Run first: python scripts/fetch_volume.py {vol}")

    pn = json.loads(pn_path.read_text())
    leaf2page = {p["leafNum"]: p.get("pageNumber") for p in pn["pages"]}

    entries: list[dict] = []
    n_par = 0
    for leaf, par_text in iter_paragraphs(chocr_path):
        n_par += 1
        if leaf is None or not par_text:
            continue
        norm = re.sub(r"\s+", " ", par_text).strip()
        # Miñano's chocr already strips end-of-line hyphens entirely
        # (probe_paragraphs.py confirmed: "anchocauce" instead of
        # "ancho-cauce"). Re-glue the rare remaining "X-Y" anyway.
        norm = re.sub(r"(\w)-(\w)", r"\1\2", norm)
        if len(norm) < 20:
            continue

        m = PAT_ENTRY_STRICT.match(norm)
        require_body_marker = False
        if not m:
            m = PAT_ENTRY_LOOSE.match(norm)
            require_body_marker = True
        if not m:
            continue
        title = _strip_title_noise(m.group("title")).strip(" .,;:-")
        body = m.group("body").strip()
        if not (3 <= len(title) <= 60):
            continue
        if sum(1 for c in title if c.isalpha()) < 3:
            continue
        if HEADER_TOKENS.match(title):
            continue
        if title.upper() in TITLE_BLACKLIST:
            continue
        if re.fullmatch(r"(?:[A-ZÑÁÉÍÓÚÜ]\.?\s*){1,3}", title):
            continue
        if require_body_marker and not BODY_MARKER.match(body):
            continue

        # Recover Balearic mentions where the OCR glued the article to
        # the place name ("delaisla", "enlaisla", …).
        body_search = re.sub(
            r'\b(la|el|las|los|en|de|del|y)(isla|Illa|isl|prov|pror|partido|cala|punta|'
            r'cabo|sierra|valle|bahia|bahía|monte|playa|puerto|tercio|distrito|'
            r'distr|dióc|adm)',
            r'\1 \2', body, flags=re.IGNORECASE)
        if not passes_balear(body_search):
            continue

        entries.append({
            "vol": vol,
            "leaf": leaf,
            "page_printed": leaf2page.get(leaf),
            "title": title,
            "context": body[:140].strip(),
        })

    # Deduplicate by (leaf, uppercased title).
    seen: set[tuple] = set()
    unique: list[dict] = []
    for e in entries:
        key = (e["leaf"], e["title"].upper())
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    print(f"  {n_par} paragraphs read, {len(entries)} raw entries, {len(unique)} unique")
    return unique


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: python scripts/index_volume.py <vol>  (e.g. 02)")
    vol = sys.argv[1].zfill(2)
    print(f"Indexing tomo {vol}...")
    entries = index_volume(vol)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"tomo{vol}.jsonl"
    with out.open("w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"Wrote {len(entries)} entries to {out.relative_to(PROJECT)}")
    print("\nFirst 8:")
    for e in entries[:8]:
        print(f"  leaf={e['leaf']:>4} p.{str(e['page_printed']):>5}  "
              f"{e['title'][:30]:30}  | {e['context'][:90]}")


if __name__ == "__main__":
    main()
