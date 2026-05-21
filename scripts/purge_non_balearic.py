"""Drop non-Balearic entries from a tomo's index.

Phase 1 (``index_volume.py``) is intentionally recall-heavy: the
double-signal filter (canonical-locator-near-Balearic-name OR ≥ 2
distinct Balearic mentions) admits peninsular homonyms whose body
happens to mention a Balearic place by coincidence.

In Tomo II that includes:

- Multiple ``CABRERA`` entries that turn out to be peninsular Cabreras
  (Sierra de Cabrera in Almería, Río Cabrera in León, jurisdicciones
  de Cabrera in León / Astorga, Cabrera de Buitrago, Cabrera de
  Sigüenza, …).
- Entries that belong to a *jurisdicción de Cabrera* in León but are
  themselves elsewhere (BENUZA, CASAYO, CASTRILLO).
- Entries that mention "Cabrera" or another Balearic word in their
  body for unrelated reasons (CASJLLAS DE MORA, BERMEO with its
  islet-cluster description elsewhere on the leaf).

This script drops them with a single discriminator that, empirically,
separates all 11 true positives from all 7 false positives in Tomo
II:

    A Balearic Miñano article anchors itself within the first ~120
    chars of its body to an EXPLICITLY BALEARIC province / island /
    diocese. Concretely, after the entry-typology header ``... de
    Esp[aña] ,``, the first geographic locator + place is one of
    ``(isla|prov.|provincia|obisp.|obispado) [...] (Mallorca | Menorca
    | Ibiza | Iviza | Formentera | Baleares)``. Anything else (``...
    prov. de León``, ``... en Vizcaya``, ``... provincia de
    Cataluña``) is peninsular by definition.

The script is idempotent and dry-run by default. Pass ``--apply`` to
write the filtered JSONL back over the input file.

Run: ``python scripts/purge_non_balearic.py <vol> [--apply]``
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"
CHOCR_DIR = DATA / "chocr"
INDEX_DIR = DATA / "index"


# --- Balearic place-name patterns ----------------------------------------
#
# Miñano's chocr is heavily OCR-scrambled. The pattern set below has to
# survive at minimum the substitutions we have already seen in Tomo II
# (``Mallovca``, ``Mallorea``, ``\Lallorca``, ``Alallorca``) and the
# ones expected per madoz/index_volume.py (mid-word digit confusions,
# l↔1↔I↔|, c↔e, o↔a↔0).
#
# Strategy mirrors ``../madoz/scripts/index_volume.py`` but with each
# character class widened a notch because Miñano's scans are older and
# noisier than Madoz's. Char-class legend:
#
#   l-family ::= [li1!|tjI]      (lowercase l, digits/punct that look l)
#   o-family ::= [oae0]          (curves with no ascender)
#   r-family ::= [rnvuti]        (mid-height verticals)
#   c-family ::= [ceova]         (open curves)
#   a-tail   ::= [aáeo]          (a/á often misread as e/o at word-end)
#   M-init   ::= [MN\\IH]        (M is often misread as N, H, IVI, A-ligature)
#   B-init   ::= [BRPDISH8]      (Bs misread as R, P, D, I, S, H, 8)
#
# The patterns intentionally do NOT require a fixed length — the OCR
# can both DROP characters mid-word (``Mllorca``) and INSERT spurious
# ones — so most positions are ``{1,2}`` rather than ``{1}``.
PAT_MALLORCA = (
    r'[MN\\IH][aáes\.4]{0,2}[li1!|tjI]{1,2}[oae0]'
    r'[rnvuti][ceova][aáeo]'
)
PAT_MENORCA = (
    r'[MN\\IH][eéfaes\.]{0,2}[nui1!|m]{1,2}[oae0]'
    r'[rnvuti][ceova][aáeo]'
)
PAT_IBIZA = (
    r'[IilJ1!|][bdh\|][iI1!|jl][zsxv][aáeo]'
)
PAT_IVIZA = (
    r'[IilJ1!|]v[iI1!|jl][zsxv][aáeo]'
)
PAT_FORMENTERA = (
    r'F[oae0]rm[eéaes][nui1!|m]t[ceova][rnvuti][aáeo]'
)
PAT_BALEARES = (
    r'[BRPDISH8][aáes4o]{1,2}[li1!|tjI][eéaeso]{1,2}r[eéaeso]s'
)
PAT_BALEAR = (  # singular, for "del Balear", "Islas Baleáricas"
    r'[BRPDISH8][aáes4o]{1,2}[li1!|tjI][eéaeso]{1,2}r[eéaeso]?[a-z]?'
)
# "Cabrera" alone is too ambiguous (Sierra de Cabrera, Río Cabrera,
# Jurisdicción de Cabrera all exist on the Peninsula). The purge
# never accepts based on Cabrera alone — we require Mallorca / Menorca
# / Ibiza / Iviza / Formentera / Baleares.

PAT_PLACE = (
    r'(?:' + PAT_MALLORCA + r'|' + PAT_MENORCA + r'|' + PAT_IBIZA + r'|'
    + PAT_IVIZA + r'|' + PAT_FORMENTERA + r'|' + PAT_BALEARES + r')'
)

# Strong-positive anchor: a geographic locator (isla / prov. / obisp. /
# diócesis / partido / adm.) immediately followed (within 30 chars) by
# a Balearic place name. The two alternatives capture the two clauses
# every real Miñano Balearic article uses to anchor itself:
#
#   - "<Type>. de Esp[aña], en la isla de Mallorca [...]"
#   - "<Type>. de España, provincia (y obispado)? de Mallorca [...]"
#
# Both arms are checked against the first ~140 chars of body, where the
# anchor always lives. ``\b`` is *not* required before the place name
# because Miñano's chocr glues determiners to the next word
# ("deMallorca", "delaisla"); see the determiner-unglue pre-pass in
# ``is_balearic`` below.
PAT_STRONG_BALEAR = re.compile(
    r'(?:'
        # (a) Locator + place name within 30 chars. OCR-tolerant:
        #   - "Illa" — Catalan-influenced spelling Miñano uses
        #   - "pror." — OCR mangle of "prov." (v→r), seen in Tomo IX BSB scan
        r'(?:isla|Isla|Illa|prov(?:incia|\.)|pror\.|partido|obisp(?:ado|\.)|'
        r'di[óo]c(?:esis|\.)|adm\.|en\s+la\s+(?:Isla|isla|Illa))'
        r'.{0,30}?'
        + PAT_PLACE +
    r'|'
        # (b) "de <place>" right after the typology header.
        r'\bde\s*' + PAT_PLACE +
    r')',
    re.IGNORECASE,
)


# OCR noise chars that ``index_volume.py`` strips from titles before
# emitting them to the JSONL (e.g. ``CABRER^A`` → ``CABRERA``). The
# purge needs the same set so it can locate the original paragraph in
# the chocr when matching the cleaned title against it.
TITLE_NOISE_RE = re.compile(r'[\^_]+')


# chOCR streaming (kept in-sync with index_volume.py).
PAGE_PAT = re.compile(r'class="ocr_page" id="page_(\d+)"')
PAR_OPEN_PAT = re.compile(r'<p class="ocr_par"')
CHAR_PAT = re.compile(r'<span class="ocrx_cinfo"[^>]*>([^<])</span>')


def iter_paragraphs(chocr_path: Path):
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


def load_paragraphs_for_leaves(chocr_path: Path, leaves: set[int]) -> dict[int, list[str]]:
    """Return {leaf -> [normalised paragraph, …]} for the requested leaves."""
    out: dict[int, list[str]] = {}
    for leaf, par in iter_paragraphs(chocr_path):
        if leaf not in leaves or not par:
            continue
        norm = re.sub(r"\s+", " ", par).strip()
        norm = re.sub(r"(\w)-(\w)", r"\1\2", norm)
        if len(norm) < 20:
            continue
        out.setdefault(leaf, []).append(norm)
    return out


def find_entry_body(paragraphs: list[str], title: str) -> str | None:
    """Locate the paragraph on a leaf that opens with ``title`` and
    return its body (after the first ``,`` or whitespace).

    The match tolerates two kinds of OCR noise that the indexer already
    normalises out of the stored title: whitespace inserted inside a
    title (``BEL VER`` matches paragraphs that open with ``BELVER`` or
    ``BEL VER``) and noise chars stripped from the title (``CABRERA``
    matches a paragraph that opens with ``CABRER^A``).
    """
    # Build a whitespace-tolerant pattern. Python 3.7+ ``re.escape``
    # escapes the space character (``"BEL VER"`` → ``"BEL\\ VER"``),
    # which would force a literal backslash to match — so we
    # ``re.escape`` each non-whitespace token separately and rejoin
    # them with ``\s*``.
    head = r"\s*".join(re.escape(tok) for tok in title.strip().split())
    for par in paragraphs:
        # Strip noise chars from the start of the paragraph the same
        # way ``index_volume.py`` did when generating the title.
        par_norm = TITLE_NOISE_RE.sub('', par)
        if re.match(rf"\s*{head}(?=[\s,\.]|$)", par_norm, re.IGNORECASE):
            m = re.match(rf"\s*{head}[\s,\.]+(.+)", par_norm,
                         re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1)
            return par_norm
    # Fall back to the first paragraph on the leaf (unlikely to be needed
    # for tomo II; left in for safety).
    return paragraphs[0] if paragraphs else None


def is_balearic(body: str) -> bool:
    """Strong-positive Balearic anchor check on the first ~140 chars."""
    head = body[:140]
    # Insert a space when OCR has glued the determiner to the next word
    # ("deMallorca" → "de Mallorca", "enlaisla" → "en la isla", …) so
    # that ``\b``-anchored sub-patterns inside PAT_STRONG_BALEAR fire.
    head = re.sub(
        r"\b(la|el|las|los|en|de|del|y)(isla|Isla|prov|provincia|partido|"
        r"obisp|Mallorca|Mallorea|Menorca|Menorea|Ibiza|Iviza|Formentera|"
        r"Baleares)",
        r"\1 \2", head,
    )
    return bool(PAT_STRONG_BALEAR.search(head))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vol", help="Two-digit tomo number (e.g. 02)")
    ap.add_argument("--apply", action="store_true",
                    help="Write the filtered JSONL back. Without this, run dry.")
    args = ap.parse_args()

    vol = args.vol.zfill(2)
    in_path = INDEX_DIR / f"tomo{vol}.jsonl"
    chocr_path = CHOCR_DIR / f"tomo{vol}.html.gz"
    if not in_path.exists():
        sys.exit(f"Missing {in_path}. Run scripts/index_volume.py {vol} first.")
    if not chocr_path.exists():
        sys.exit(f"Missing {chocr_path}. Run scripts/fetch_volume.py {vol} first.")

    entries = [json.loads(l) for l in in_path.open()]
    print(f"Loaded {len(entries)} entries from {in_path.relative_to(PROJECT)}")

    # Re-load full paragraphs for every (vol, leaf) we touch.
    leaves = {e["leaf"] for e in entries}
    paras = load_paragraphs_for_leaves(chocr_path, leaves)

    kept: list[dict] = []
    dropped: list[dict] = []
    for e in entries:
        body = find_entry_body(paras.get(e["leaf"], []), e["title"])
        if body is None:
            # Couldn't relocate the paragraph. Conservatively drop so
            # we don't carry stale entries forward.
            dropped.append({**e, "reason": "paragraph not found in chocr"})
            continue
        if is_balearic(body):
            kept.append(e)
        else:
            dropped.append({**e, "reason": "no Balearic anchor in body head",
                            "body_head": body[:140]})

    print(f"\nKept   {len(kept):>3} entries")
    print(f"Dropped {len(dropped):>3} entries")
    print("\n--- Dropped ---")
    for d in dropped:
        head = d.get("body_head", "(missing)")
        print(f"  leaf={d['leaf']:>4} p.{str(d.get('page_printed')):>5}  "
              f"{d['title'][:28]:28} | {head[:110]}")

    if not args.apply:
        print("\n(dry run — pass --apply to overwrite the JSONL)")
        return

    with in_path.open("w") as f:
        for e in kept:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(kept)} entries back to {in_path.relative_to(PROJECT)}")


if __name__ == "__main__":
    main()
