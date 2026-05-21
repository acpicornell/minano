"""Phase 3 — extract structured Miñano entries from chocr TEXT.

Port of ``../madoz/scripts/extract_text.py``. Same shape: for each
target leaf send Claude the chocr text of that leaf plus a window of
continuation leaves, ask it to emit one structured record per Balearic
entry whose TITLE is on the target leaf.

The Miñano-specific changes from madoz are:

- Source-of-truth is ``data/index/tomo<vol>.jsonl`` (the per-tomo
  index that ``index_volume.py`` + ``purge_non_balearic.py`` +
  ``fix_ocr_titles.py`` produced). madoz reads from a DuckDB
  table; we don't have one yet.
- ``SYSTEM_PROMPT`` updates the dates (1826-1829) and the
  abbreviation set (``V. R./V. S./L. R./Ald./Castillo/Jurisd.``,
  ``A. O./A. P.``, ``Contribuye con Palma``, …).
- ``ENTRY_SCHEMA`` swaps ``judicial_district`` (anachronistic — the
  partido judicial reform is from 1834) for the two
  attributes Miñano always stamps: ``seigneurial_regime`` (R/S/Ab/
  Ord/Ecl) and ``mayor_type`` (Ordinario/Pedáneo).

Modes:
  --page VOL LEAF       extract a single leaf (testing)
  --sample VOL          run on a small curated sample of the tomo
  --all VOL             process every leaf in tomo's index

Output: ``data/text/page_<vol>_<leaf>.json`` — one file per leaf.

Requires ``ANTHROPIC_API_KEY`` in env (loaded from .env).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PROJECT = Path(__file__).resolve().parent.parent
CHOCR_DIR = PROJECT / "data" / "chocr"
INDEX_DIR = PROJECT / "data" / "index"
OUT_DIR = PROJECT / "data" / "text"

DEFAULT_MODEL = "claude-sonnet-4-6"
MODEL_PRICING = {
    "claude-opus-4-7":           {"in": 15.00, "out": 75.00},
    "claude-sonnet-4-6":         {"in": 3.00,  "out": 15.00},
    "claude-haiku-4-5-20251001": {"in": 1.00,  "out": 5.00},
}

PAGE_PAT = re.compile(r'class="ocr_page" id="page_(\d+)"')
PAR_OPEN_PAT = re.compile(r'<p class="ocr_par"')
CHAR_PAT = re.compile(r'<span class="ocrx_cinfo"[^>]*>([^<])</span>')


# ---------- chOCR text loading (identical to madoz) ------------------------

def leaf_paragraphs(chocr_path: Path, target_leaves: set[int]) -> dict[int, list[str]]:
    """Return {leaf: [paragraph_text, ...]} for each target leaf.

    Streams the gzipped chocr file. Stops early once the current leaf
    number is past max(target_leaves).
    """
    opener = gzip.open if chocr_path.suffix == ".gz" else open
    out: dict[int, list[str]] = {leaf: [] for leaf in target_leaves}
    current_leaf: int | None = None
    in_par = False
    buf: list[str] = []
    max_leaf = max(target_leaves)
    with opener(chocr_path, "rt", encoding="utf-8") as f:
        for line in f:
            m_page = PAGE_PAT.search(line)
            if m_page:
                if in_par and buf and current_leaf in out:
                    out[current_leaf].append("".join(buf))
                buf = []
                in_par = False
                current_leaf = int(m_page.group(1))
                if current_leaf > max_leaf:
                    break
                continue
            if PAR_OPEN_PAT.search(line):
                if in_par and buf and current_leaf in out:
                    out[current_leaf].append("".join(buf))
                buf = []
                in_par = True
                continue
            if "</p>" in line:
                if in_par and buf and current_leaf in out:
                    out[current_leaf].append("".join(buf))
                buf = []
                in_par = False
                continue
            if in_par and current_leaf in out:
                for cm in CHAR_PAT.finditer(line):
                    buf.append(cm.group(1))
    return out


def normalize_paragraph(text: str) -> str:
    """Collapse whitespace and re-join hyphenated line-end breaks.

    Note: Miñano's Google chocr already drops most end-of-line
    hyphens (see ``probe_paragraphs.py`` calibration), but a few
    survive. We re-glue them defensively.
    """
    norm = re.sub(r"\s+", " ", text).strip()
    norm = re.sub(r"(\w)-\s*(\w)", r"\1\2", norm)
    return norm


def build_leaf_text(
    chocr_path: Path, leaf: int, window: int = 2
) -> tuple[str, list[str]]:
    """Return (target_leaf_text, [continuation_leaf_text, ...])."""
    if window < 1:
        raise ValueError("window must be ≥1")
    targets = set(range(leaf, leaf + window))
    pars = leaf_paragraphs(chocr_path, targets)
    target_text = "\n\n".join(
        normalize_paragraph(p) for p in pars.get(leaf, []) if p.strip()
    )
    continuations: list[str] = []
    for offset in range(1, window):
        nl_pars = pars.get(leaf + offset, [])
        nl_text = "\n\n".join(normalize_paragraph(p) for p in nl_pars if p.strip())
        if nl_text:
            continuations.append(nl_text)
    return target_text, continuations


# ---------- Index loading -------------------------------------------------

def load_index(vol: str) -> list[dict]:
    """Read ``data/index/tomo<vol>.jsonl``."""
    p = INDEX_DIR / f"tomo{vol}.jsonl"
    if not p.exists():
        raise FileNotFoundError(
            f"Missing {p}. Run scripts/index_volume.py {vol} first."
        )
    return [json.loads(l) for l in p.open()]


def entries_for_leaf(index: list[dict], vol: str, leaf: int) -> list[dict]:
    return [e for e in index if e["vol"] == vol and e["leaf"] == leaf]


# ---------- Tool schema ---------------------------------------------------
#
# Same shape as madoz: Claude must call the tool exactly once with the
# full list of entries on the leaf. Schema fields adapted for Miñano.

ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": (
                "Cleaned canonical title as printed by Miñano, in ALL "
                "CAPS, with any parenthetical specifier preserved "
                "literally (e.g. 'BINISALEM', 'CABRERA (Isla de)', "
                "'CAP DE PERA'). Restore obvious OCR mangles "
                "(missing accents, R↔U, V↔Y) from context but keep "
                "Miñano's 1826 hispanicised spellings (CAIMARY, "
                "BÜÑOLA, CALVIA) — do NOT modernise to current "
                "Catalan toponyms."
            ),
        },
        "place_type": {
            "type": "string",
            "description": (
                "Spanish lemma for the entry type, lowercase. Miñano's "
                "single-letter typology expands to: V.=villa, "
                "L.=lugar, C.=ciudad, Ald.=aldea, Cas.=caserío, "
                "Castillo, Jurisd.=jurisdicción, Herm.=hermandad, "
                "Cot.=coto, Desp.=despoblado, Felig.=feligresía, "
                "Parr.=parroquia, Pred.=predio. For natural features "
                "use the noun directly ('isla', 'cala', 'punta', "
                "'cabo', 'sierra', 'monte', 'valle', 'río', 'arroyo')."
            ),
        },
        "island": {
            "type": "string",
            "enum": ["Mallorca", "Menorca", "Ibiza", "Formentera", "Cabrera"],
            "description": (
                "Balearic island the entry belongs to. Use 'Ibiza' "
                "for Miñano's 'Iviza' spelling."
            ),
        },
        "seigneurial_regime": {
            "type": "string",
            "enum": ["Realengo", "Señorial", "Abadengo", "de Órdenes",
                     "Eclesiástico", "Mixto", "Otro"],
            "description": (
                "The jurisdiction Miñano stamps next to the type "
                "abbreviation. Decoding: 'R.'=Realengo (crown), "
                "'S.'=Señorial (nobility), 'Ab.'=Abadengo (monastic), "
                "'Ord.'=de Órdenes (military orders), "
                "'Ecl.'=Eclesiástico (church). Null if Miñano did not "
                "stamp one (typical for natural features, castles)."
            ),
        },
        "mayor_type": {
            "type": "string",
            "enum": ["Alcalde Ordinario", "Alcalde Pedáneo",
                     "Alcalde Mayor", "Sin alcalde", "Otro"],
            "description": (
                "The 'A. O.' / 'A. P.' marker Miñano writes before "
                "the population figures. 'A. O.' = Alcalde Ordinario "
                "(first instance jurisdiction), 'A. P.' = Pedáneo "
                "(lower rank, depends on a higher-ranked town), "
                "'No hay alcalde' = Sin alcalde. Null if not stated."
            ),
        },
        "municipality": {
            "type": "string",
            "description": (
                "The town this entry depends on for civil/ecclesiastical "
                "administration or tax (e.g. 'Palma', 'Selva', "
                "'Santañy'). Comes from phrases like 'depende de X' or "
                "'aneja de X' or 'Contribuye con X'. Null if not "
                "specified."
            ),
        },
        "description": {
            "type": "string",
            "description": (
                "Full cleaned transcription of the entry's body. Repair "
                "OCR glue ('islade Mallorca' → 'isla de Mallorca', "
                "'V.S.deEsp.' → 'V. S. de Esp.') and obvious "
                "letter-level OCR confusion (1↔i↔l, 0↔o, 5↔s, 8↔b) "
                "but preserve Miñano's abbreviation style verbatim "
                "('prov.', 'obisp.', 'aud.', 'A. O.', 'vec.', 'hab.', "
                "'Contr. con Palma', 'V. la descripción general de "
                "Mallorca'). Do NOT modernise his spellings."
            ),
        },
        "stats": {
            "type": "object",
            "description": (
                "Population & contribution figures Miñano inlines in "
                "the body. Common keys: 'vecinos' (households), "
                "'habitantes' (souls), 'parroquias', 'conventos', "
                "'contribuye_con' (the town that pays tax). For "
                "ambiguous OCR digits set the field but mark "
                "confidence 'low'."
            ),
            "additionalProperties": True,
        },
        "cross_references": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Other Miñano entries this one points to via 'V. X' "
                "(véase) or 'Véase la descripción general de X' or "
                "'(V. este art.)'. Empty array if none."
            ),
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": (
                "Your confidence in the structured fields given that "
                "the INPUT IS chocr-text (not the facsimile). 'low' "
                "when OCR was so garbled key fields had to be guessed; "
                "'medium' for moderate ambiguity especially in numeric "
                "stats; 'high' for clean, unambiguous extraction."
            ),
        },
    },
    "required": ["title", "description", "confidence"],
    "additionalProperties": False,
}

TOOL = {
    "name": "record_leaf_entries",
    "description": (
        "Record every Balearic Miñano dictionary entry whose TITLE "
        "appears on the target leaf. One call, with the full list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": ENTRY_SCHEMA,
                "description": "All Balearic entries titled on the target leaf.",
            },
        },
        "required": ["entries"],
    },
}

SYSTEM_PROMPT = """\
You extract structured records from OCR'd text of Sebastián de Miñano's
"Diccionario geográfico-estadístico de España y Portugal" (Madrid,
1826-1829, 11 vols.). The OCR is from a 19th-century two-column
facsimile via Google Books / Internet Archive and is noisy: expect
mangled digits (1↔i↔l, 0↔o, 5↔s, 8↔b), broken accents, glued or split
words ("islade Mallorca", "V.S.deEsp."), stray glyphs (^ inside
"CABRER^A"), and letter-class confusions (R↔U at word-end, e↔c, n↔ti).

We care ONLY about Balearic entries — those whose geographic context
names Mallorca/Mallorea, Menorca/Menorea, Ibiza/Iviza, Formentera or
Cabrera (the islet south of Mallorca, NOT the peninsular Sierra de
Cabrera in León/Almería). Skip non-Balearic entries that share the
leaf.

Each Miñano entry begins with a TITLE in caps followed by a COMMA (the
canonical separator; the OCR sometimes drops it). The body opens with
a typology header in the shape "<Type>. <Regime>. de Esp[aña]." where:

  Type: V.=villa, L.=lugar, C.=ciudad, Ald.=aldea (often OCR'd Aid.),
        Cas.=caserío, Cot.=coto, Desp.=despoblado (OCR Dcsp.),
        Castillo, Jurisd.=jurisdicción, Herm.=hermandad, Pred.=predio.
  Regime: R.=Realengo, S.=Señorial, Ab.=Abadengo, Ord.=de Órdenes,
          Ecl.=Eclesiástico.

Then a geographic placement ("en la isla de Mallorca y de su obispado",
"provincia y obisp. de Mallorca"), an administrative marker
("A. O." = Alcalde Ordinario, "A. P." = Alcalde Pedáneo, "No hay
alcalde"), inline population figures ("76 vec., 318 hab.", "Sit. á 6
leguas de la capital"), and often a tax pointer ("Contribuye con
Palma", "Contr. con Palma"). Cross-references take the form "V. NAME"
or "Véase la descripción general de Mallorca".

You will receive the chocr text for one target leaf plus the next leaf
as continuation context. Emit ONE record per entry whose TITLE is on
the target leaf — including the full body even if it spills into the
next leaf. Do NOT emit entries that are only continuations of an entry
titled on a previous leaf.

When OCR is uncertain, use context, neighboring entries and standard
Miñano abbreviations to repair. Restore obvious OCR damage ("BUGEU"
→ "BUGER" when the body mentions "aneja la de Buger") but preserve
Miñano's authentic 1826 hispanicised spellings ("CAIMARY", "BÜÑOLA",
"CALVIA", "BINARAÜS") — do NOT modernise to current Catalan toponyms.
For numeric fields prefer the OCR digits but if they're clearly broken
(e.g. "32g" for "329"), set the field to your best guess and mark
confidence 'low'.

Call the `record_leaf_entries` tool exactly once with the full list.\
"""


# ---------- Window sizing -------------------------------------------------
#
# Miñano's mega-articles, when we reach them in tomos V-VII, will be
# MALLORCA, MENORCA, MAHON, PALMA, IBIZA, IVIZA, CIUDADELA, ALCUDIA.
# We don't index those leaves yet, but the policy is the same as madoz:
# widen the window if a known mega-lemma is titled on the leaf.
MEGA_TITLES = {
    "MALLORCA", "MENORCA", "MAHON", "MAHÓN", "PALMA",
    "IBIZA", "IVIZA", "CIUDADELA", "ALCUDIA", "MANACOR",
    "BALEARES",
}


def pick_window(entries: list[dict]) -> int:
    """Return chocr-text window size (in leaves) for the target.

    Default 2 (target + 1 continuation) is enough for the typical
    short Miñano entry; 4 for known mega-lemmas.
    """
    for e in entries:
        base = e["title"].split("(")[0].strip().upper()
        if base in MEGA_TITLES:
            return 4
    return 2


# ---------- Extraction ----------------------------------------------------

def build_user_message(
    vol: str,
    leaf: int,
    page_printed: str | None,
    index_entries: list[dict],
    leaf_text: str,
    continuation_texts: list[str],
) -> str:
    titles_hint = "\n".join(
        f"  - {e['title']}" for e in index_entries
    )
    sections = [
        f"Volume tom {vol}, target leaf {leaf}, printed page "
        f"{page_printed or '?'}.\n",
        f"Our prior chocr index identified these {len(index_entries)} "
        f"Balearic entries titled on this leaf (titles may carry OCR "
        f"noise; trust the text below):\n{titles_hint}\n",
        "=== TARGET LEAF (chocr text) ===\n" + leaf_text,
    ]
    for i, cont in enumerate(continuation_texts, start=1):
        sections.append(
            f"\n=== CONTINUATION LEAF +{i} (do NOT emit entries titled "
            f"here) ===\n{cont}"
        )
    sections.append(
        "\nExtract every Balearic entry whose TITLE appears on the "
        "TARGET leaf. Include the full body even if it spills into "
        "the continuation leaves."
    )
    return "\n".join(sections)


def extract_leaf(
    client: anthropic.Anthropic,
    vol: str,
    leaf: int,
    index: list[dict],
    model: str = DEFAULT_MODEL,
) -> dict:
    chocr_path = CHOCR_DIR / f"tomo{vol}.html.gz"
    if not chocr_path.exists():
        raise FileNotFoundError(f"chocr missing: {chocr_path}")

    leaf_entries = entries_for_leaf(index, vol, leaf)
    if not leaf_entries:
        raise ValueError(
            f"No indexed entries for vol={vol} leaf={leaf}. "
            f"Did purge_non_balearic.py drop them all?"
        )
    page_printed = leaf_entries[0].get("page_printed")
    window = pick_window(leaf_entries)
    leaf_text, continuations = build_leaf_text(chocr_path, leaf, window=window)
    user_text = build_user_message(
        vol, leaf, page_printed, leaf_entries, leaf_text, continuations
    )

    msg = client.messages.create(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_leaf_entries"},
        messages=[{"role": "user", "content": user_text}],
    )

    payload = None
    for block in msg.content:
        if block.type == "tool_use" and block.name == "record_leaf_entries":
            payload = block.input
            break
    if payload is None:
        raise RuntimeError(
            "Model did not call the expected tool. content blocks: "
            + str([b.type for b in msg.content])
        )

    return {
        "vol": vol,
        "leaf": leaf,
        "page_printed": page_printed,
        "model": model,
        "window": window,
        "usage": {
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        },
        "entries": payload["entries"],
        "chocr_text_leaf": leaf_text,
        "chocr_text_continuations": continuations,
    }


# ---------- Sample picker -------------------------------------------------

def pick_sample(index: list[dict], vol: str) -> list[tuple[str, int]]:
    """Return a small diverse leaf sample for ``--sample``.

    Strategy: pick leaves that exercise the three interesting cases —
    single-entry leaf, multi-entry leaf, and a leaf whose title needed
    the noise-tolerant indexer pass (recovered via ``^_``). Falls back
    to the first three distinct leaves if the corpus is too small.
    """
    by_leaf: dict[int, list[dict]] = {}
    for e in index:
        if e["vol"] == vol:
            by_leaf.setdefault(e["leaf"], []).append(e)

    if not by_leaf:
        return []

    chosen: list[int] = []
    # Multi-entry leaf.
    multi = sorted((leaf for leaf, es in by_leaf.items() if len(es) >= 2))
    if multi:
        chosen.append(multi[0])
    # Recovered-noisy-title leaf (any entry whose title would have
    # required the noise pass — for tomo II, CABRERA Isla de on leaf 255).
    for leaf, es in sorted(by_leaf.items()):
        if any("Isla" in e["title"] for e in es) and leaf not in chosen:
            chosen.append(leaf)
            break
    # Single-entry leaf.
    for leaf, es in sorted(by_leaf.items()):
        if len(es) == 1 and leaf not in chosen:
            chosen.append(leaf)
            break
    # Backfill with the first leaves if we got fewer than 3.
    for leaf in sorted(by_leaf):
        if leaf in chosen:
            continue
        chosen.append(leaf)
        if len(chosen) >= 3:
            break

    return [(vol, leaf) for leaf in chosen[:3]]


# ---------- CLI -----------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_mutually_exclusive_group(required=True)
    sub.add_argument("--page", nargs=2, metavar=("VOL", "LEAF"),
                     help="extract a single leaf (e.g. --page 02 137)")
    sub.add_argument("--sample", metavar="VOL",
                     help="run on a small curated sample of this tomo")
    sub.add_argument("--all", metavar="VOL",
                     help="process every leaf in tomo<VOL>.jsonl")
    ap.add_argument("--overwrite", action="store_true",
                    help="re-extract leaves even if their JSON already exists")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    choices=list(MODEL_PRICING),
                    help=f"model to use (default {DEFAULT_MODEL})")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set in environment (or .env).")
    client = anthropic.Anthropic()

    if args.page:
        vol, leaf = args.page[0].zfill(2), int(args.page[1])
        index = load_index(vol)
        pairs = [(vol, leaf)]
    elif args.sample:
        vol = args.sample.zfill(2)
        index = load_index(vol)
        pairs = pick_sample(index, vol)
        print(f"Sample for tomo {vol}: {[l for _, l in pairs]}")
    else:
        vol = args.all.zfill(2)
        index = load_index(vol)
        leaves = sorted({e["leaf"] for e in index if e["vol"] == vol})
        pairs = [(vol, leaf) for leaf in leaves]
        print(f"All leaves in tomo {vol}: {len(pairs)}")

    suffix = "" if args.model == DEFAULT_MODEL else f"_{args.model.split('-')[1]}"
    total_in = total_out = 0
    for vol, leaf in pairs:
        out_path = OUT_DIR / f"page_{vol}_{leaf}{suffix}.json"
        if out_path.exists() and not args.overwrite:
            print(f"  [skip] {out_path.name} already exists")
            continue
        try:
            print(f"  [GET]  tom{vol} leaf{leaf} ({args.model})...", flush=True)
            result = extract_leaf(client, vol, leaf, index, model=args.model)
        except FileNotFoundError as e:
            print(f"  [skip] {e}")
            continue
        except Exception as e:
            print(f"  [fail] tom{vol} leaf{leaf}: {e}", file=sys.stderr)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        ti = result["usage"]["input_tokens"]
        to = result["usage"]["output_tokens"]
        total_in += ti
        total_out += to
        print(f"  [ok]   {out_path.name}: {len(result['entries'])} entries "
              f"(in={ti} out={to} toks)")
        time.sleep(0.2)

    if total_in or total_out:
        rate = MODEL_PRICING[args.model]
        cost = total_in / 1_000_000 * rate["in"] + total_out / 1_000_000 * rate["out"]
        print()
        print(f"Tokens: in={total_in:,}  out={total_out:,}  ({args.model})")
        print(f"Estimated cost (non-batch): ${cost:.4f}")


if __name__ == "__main__":
    main()
