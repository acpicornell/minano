#!/usr/bin/env python3
"""Audit chOCR paragraphs for Balearic lemmas buried mid-paragraph.

The main indexer (``scripts/index_volume.py``) matches Miñano lemmas
anchored to the start of a chOCR paragraph: it expects each article
to begin its own paragraph block. The chOCR sometimes fails to break
between consecutive articles, however, and a Balearic entry can end
up sharing a paragraph with the tail of the preceding (often
peninsular) one. In that situation the indexer is blind to the
buried article.

Two distinct miss patterns motivate this audit:

A) **Tail-merge** — a Balearic article begins mid-paragraph because
   the chOCR did not break between it and the preceding (often
   peninsular) entry. SINEU (Tom VIII, leaf 308, merged with the
   tail of SINES of Portugal) and RUBERTS (Tom VII, leaf 375,
   merged with the tail of QUINTANAPALLA) are the canonical
   examples. The lemma here looks like a full article opener:
   «TITLE, V.|L.|C.|Ald. de Esp. en la isla de Mallorca…».

B) **Chained Suplement corrections** — a single paragraph of the
   Suplement (tomo XI) carries a sequence of very short adicions,
   each headed by «Title.» (often Titlecase, not full caps) and
   followed by a brief correction («Tiene 453 habitantes», «No
   tiene alcalde», «léase…»). The indexer captures only the first
   item of the chain because it expects each article in its own
   paragraph. The leaf 152 paragraph of tomo XI carried at least
   five adicions (Binaraus, Biniagual, Biniali, Biniamar,
   Biniaraig) of which only Biniagual had been extracted.

Both patterns are scanned. Candidates whose title is already
represented in ``data/text/`` (fuzzy WRatio ≥ 80) are dropped;
peninsular false positives are filtered by an explicit Balearic
anchor requirement within ~250 characters of the candidate.

Run periodically — for example after a fresh extraction pass — to
verify that no Balearic article has been silently merged into a
neighbouring entry.

Usage:
    python scripts/inner_lemma_audit.py                # all tomos
    python scripts/inner_lemma_audit.py --vol 08       # one tomo
    python scripts/inner_lemma_audit.py --pattern A    # restrict to
                                                       # one pattern
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_gazetteer import normalize  # noqa: E402
from extract_text import leaf_paragraphs, normalize_paragraph  # noqa: E402

CHOCR = ROOT / "data" / "chocr"
TEXT = ROOT / "data" / "text"

# Pattern A — full-article opener buried mid-paragraph.
INNER_LEMMA = re.compile(
    r"(?<![A-ZÁÉÍÓÚÑÜa-záéíóúñü0-9])"
    r"([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\d\-\']{2,18}"
    r"(?:\s+[A-ZÁÉÍÓÚÑÜ\d\-\.,()]{1,15}){0,3})"
    r"\s*,\s*"
    r"(V|L|C|Ald|Aid|Cas|Cot|Desp|Felig|Parr|Jurisd|R|S)\.?"
)

# Pattern B — Suplement-style chained correction. The leading lemma
# is followed by a period (sometimes the OCR drops it) and then one
# of a small set of opener verbs/abbreviations characteristic of
# Miñano's short adicions. Titlecase is allowed (the Suplement does
# not consistently CAPS its inline lemmas), but the first character
# must be a capital. The minimum lemma length of 5 keeps Spanish
# function words (Sit, Una, Aid as a standalone) from triggering.
SUPLEMENT_LEMMA = re.compile(
    r"(?<=[\.\)\s])"
    r"([A-ZÁÉÍÓÚÑÜ][A-Za-záéíóúñüÁÉÍÓÚÑÜ\-\']{4,20})"
    r"\.?\s+"
    r"(?:Tiene|No tiene|Hay|Hubo|"
    r"Aid\.|Ald\.|L\.|V\.|C\.|Cot\.|Cas\.|Desp\.|Felig\.|"
    r"Isla\.|Cabo\.|Puerto\.|Predio\.|Cortijo\.|"
    r"Sit\.|Está sit|"
    r"En la lín|donde dice|léase|Léase|"
    r"Es ane|Era ane|Tiene por ane|"
    r"Cuando|Pertenec|Debe decir)"
)

# Opener verbs that strongly indicate a Suplement correction (rather
# than incidental sentence text). Used to confirm a hit when the
# match looks weak.
SUPLEMENT_VERBS = {
    "Tiene", "No tiene", "Hay", "Hubo", "Sit.", "Está sit",
    "En la lín", "donde dice", "léase", "Léase", "Es ane",
    "Era ane", "Tiene por ane", "Cuando", "Pertenec",
}

BALEARIC_ANCHOR = re.compile(
    r"(?:Mallorca|Menorca|Iv[iy]za|Ibiza|Eivissa|Formentera|Cabrera|Baleares|"
    r"Palma|Mahon|Mahón|isla y obisp|en la isla)",
    re.IGNORECASE,
)

# A stricter anchor used by the Suplement chained-corrections pass.
# The generic anchor above is permissive enough that peninsular
# Suplement adicions containing «Cabrera» (the León-province
# district) or «Palma» (e.g. Palma del Río) survive the body check.
# Restrict the chained pass to phrases that can only refer to the
# Balearic archipelago.
STRICT_BALEARIC_ANCHOR = re.compile(
    r"(?:Mallorca|Menorca|Iv[iy]za|Ibiza|Eivissa|Formentera|"
    r"isla de Cabrera|las Baleares|isla y ob\.|isla y obisp|en la isla)",
    re.IGNORECASE,
)

# Tokens that occasionally trigger SUPLEMENT_LEMMA but are not place
# names — they are common Spanish words that happen to start a
# sentence with a Titlecase pattern.
STOPWORDS = {
    "Aragón", "Asturias", "Cataluña", "Galicia", "Navarra", "Castilla",
    "España", "Iglesia", "Bula", "Cuando", "Pertenec", "Tiene", "Estado",
    "Mallorca", "Menorca", "Ibiza", "Iviza", "Eivissa", "Formentera",
    "Cabrera", "Baleares", "Palma", "Mahon", "Mahón", "Madrid",
    "Diciembre", "Enero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
    "Agosto", "Septiembre", "Octubre", "Noviembre", "Febrero",
    "Domingo", "Lunes", "Martes", "Jueves", "Viernes", "Sábado",
    # Editorial imperatives that look Titlecase but are verbs.
    "Bórrese", "Borrese", "Léase", "Lease", "Véase", "Vease",
    "Añádase", "Añadase", "Diccionario", "Suplemento",
}


def load_existing_titles() -> dict[str, set[str]]:
    by_vol: dict[str, set[str]] = {}
    for jp in sorted(TEXT.glob("page_*.json")):
        d = json.loads(jp.read_text())
        for e in d.get("entries", []):
            by_vol.setdefault(d["vol"], set()).add(normalize(e["title"]))
    return by_vol


def _is_known(title: str, vol: str, by_vol: dict[str, set[str]]) -> bool:
    norm_t = normalize(title)
    if not norm_t:
        return True
    # Strip an «(adición)» suffix used in our corpus when checking.
    norm_t_bare = re.sub(r"\s*\(adicio?n[es]?\)\s*$", "", norm_t).strip()
    pool = by_vol.get(vol, set())
    return any(
        fuzz.WRatio(norm_t, t) >= 80 or fuzz.WRatio(norm_t_bare, t) >= 80
        for t in pool
    )


def scan_pattern_a(vol: str, by_vol: dict[str, set[str]]):
    """Pattern A — full-article opener buried mid-paragraph."""
    chocr = CHOCR / f"tomo{vol}.html.gz"
    if not chocr.exists():
        return []
    candidates = []
    pars_by_leaf = leaf_paragraphs(chocr, set(range(700)))
    for leaf, paras in pars_by_leaf.items():
        for para in paras:
            txt = normalize_paragraph(para)
            if not txt or len(txt) < 60:
                continue
            for m in INNER_LEMMA.finditer(txt):
                if m.start() < 30:
                    continue
                title_raw = m.group(1).strip()
                first_word = title_raw.split()[0]
                if not re.match(r"^[A-ZÁÉÍÓÚÑÜ]{3,}$", first_word):
                    continue
                tail = txt[m.end():m.end() + 250]
                if not BALEARIC_ANCHOR.search(tail):
                    continue
                if _is_known(title_raw, vol, by_vol):
                    continue
                ctx = txt[max(0, m.start() - 50):m.start() + 250]
                candidates.append((leaf, title_raw, ctx, "A"))
    return candidates


def scan_pattern_b(vol: str, by_vol: dict[str, set[str]]):
    """Pattern B — Suplement chained corrections.

    Each match's correction body is bounded to the next chained
    correction (or paragraph end). The Balearic anchor must occur
    inside that bounded body, not elsewhere in the paragraph, so
    that peninsular adicions chained with Balearic ones (very
    common, since the Suplement is alphabetic) do not contaminate.
    """
    chocr = CHOCR / f"tomo{vol}.html.gz"
    if not chocr.exists():
        return []
    candidates = []
    pars_by_leaf = leaf_paragraphs(chocr, set(range(700)))
    for leaf, paras in pars_by_leaf.items():
        for para in paras:
            txt = normalize_paragraph(para)
            if not txt or len(txt) < 80:
                continue
            # Quick filter — a chained Suplement paragraph almost
            # always carries at least one Vilafranca-style signature
            # or a "léase" / "donde dice" / "Tiene" correction.
            if not re.search(
                r"(?:Not\.\s*dada\s*por|léase|donde dice|Tiene\s+\d|"
                r"se incluyen con los de|de la que depende en lo civil)",
                txt,
            ):
                continue
            matches = list(SUPLEMENT_LEMMA.finditer(txt))
            for i, m in enumerate(matches):
                if m.start() < 20:
                    continue
                title_raw = m.group(1).strip()
                if title_raw in STOPWORDS:
                    continue
                if re.search(
                    r"(?:aba|aban|ando|ó|aron|ía|ían|iendo|iente|ió)$",
                    title_raw,
                ):
                    continue
                # Bound the correction body to the next chained
                # correction in the same paragraph, capped at 350
                # characters. Critically: the Balearic anchor must
                # appear *inside this bounded body*, not in the
                # Vilafranca signature of an unrelated neighbouring
                # correction.
                body_end = (
                    matches[i + 1].start() if i + 1 < len(matches) else len(txt)
                )
                body_end = min(body_end, m.end() + 350)
                body = txt[m.end():body_end]
                # Accept either an unambiguous Balearic toponym or a
                # Vilafranca attribution (Fra Lluís de Vilafranca was
                # Miñano's exclusive Balearic correspondent, so his
                # signature in the body is a reliable Balearic mark
                # for corrections whose own text mentions only
                # Palma/Lluch/Puigmayor — locally unambiguous but
                # individually ambiguous toponyms).
                if not (
                    STRICT_BALEARIC_ANCHOR.search(body)
                    or re.search(
                        r"(?:Villafranca|Vilafranca|por el mismo|"
                        r"Lluch|Puigmayor)",
                        body,
                    )
                ):
                    continue
                # Discard peninsular false positives whose body
                # carries an unambiguously peninsular province name.
                if re.search(
                    r"\b(?:Aragón|Asturias|Cataluña|Galicia|Navarra|"
                    r"Castilla|León|Andalucía|Extremadura|Murcia|"
                    r"Valencia|Granada|Sevilla|Sigüenza|Soria|Cuenca|"
                    r"Lugo|Oviedo|Pamplona|Burgos|Madrid|Toledo|"
                    r"Salamanca|Zaragoza|Huesca|Barbastro|Jaca|"
                    r"Mondoñedo|Santiago|Tarragona|Mondéjar)\b",
                    body,
                ):
                    continue
                if _is_known(title_raw, vol, by_vol):
                    continue
                ctx = txt[max(0, m.start() - 60):m.start() + 250]
                candidates.append((leaf, title_raw, ctx, "B"))
    return candidates


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vol", help="restrict to one tomo (e.g. 08)")
    ap.add_argument(
        "--pattern",
        choices=("A", "B", "both"),
        default="both",
        help="A=tail-merge openers, B=Suplement chained corrections",
    )
    args = ap.parse_args()

    if args.vol:
        vols = [args.vol.zfill(2)]
    else:
        vols = sorted(
            re.match(r"tomo(\d+)", p.name).group(1)
            for p in CHOCR.glob("tomo*.html.gz")
        )

    by_vol = load_existing_titles()
    grand_total = 0
    for vol in vols:
        cands: list = []
        if args.pattern in ("A", "both"):
            cands += scan_pattern_a(vol, by_vol)
        if args.pattern in ("B", "both"):
            cands += scan_pattern_b(vol, by_vol)
        if not cands:
            print(f"=== Tom {vol}: clean ===", file=sys.stderr)
            continue
        print(f"\n=== Tom {vol}: {len(cands)} candidate(s) ===")
        for leaf, title, ctx, pat in cands:
            print(f"\n  leaf {leaf} [{pat}]: {title!r}")
            print(f"    {ctx!r}")
            grand_total += 1
    print(
        f"\n=== Total: {grand_total} candidate(s) across {len(vols)} tomo(s) ===",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
