-- Schema for the minano project (Balearic subset of Sebastián de
-- Miñano's Diccionario geográfico-estadístico de España y Portugal,
-- 1826-1829, 11 vols.).
--
-- One canonical table: text_entries, the Claude-extracted structured
-- articles. The chocr regex index (data/index/tomo<vol>.jsonl) is
-- *not* loaded into the DB — it is a per-tomo build artifact used by
-- extract_text.py; the JSONL stays the source of truth.
--
-- No madoz_entries-equivalent table: no third-party WordPress mirror
-- of Miñano exists. Cross-reference will be against the BNE or BDH
-- digital facsimiles directly (page-image links), if needed.

CREATE SEQUENCE IF NOT EXISTS seq_text_id START 1;

CREATE TABLE IF NOT EXISTS text_entries (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('seq_text_id'),
    vol                 TEXT NOT NULL,           -- '01' .. '11'
    leaf                INTEGER NOT NULL,
    page_printed        TEXT,
    title               TEXT NOT NULL,            -- as cleaned by the LLM
    place_type          TEXT,                    -- villa / lugar / aldea / castillo / isla / …
    island              TEXT,                    -- Mallorca / Menorca / Ibiza / Formentera / Cabrera
    -- Miñano-specific administrative attributes (the 1826 reform
    -- predates Madoz's "partido judicial"; instead every civil entry
    -- carries a seigneurial regime and an alcalde type).
    seigneurial_regime  TEXT,                    -- Realengo / Señorial / Abadengo / de Órdenes / Eclesiástico
    mayor_type          TEXT,                    -- Alcalde Ordinario / Pedáneo / Sin alcalde / …
    municipality        TEXT,                    -- Town the entry depends on (Palma, Selva, …)
    description         TEXT,                    -- cleaned transcription of the body
    stats               JSON,                    -- {vecinos, habitantes, parroquias, …}
    cross_references    TEXT[],                  -- e.g. ["V. la descripción general de Mallorca"]
    confidence          TEXT,                    -- 'high' | 'medium' | 'low'
    -- Multi-leaf window used at extraction time. 2 = target + 1 next leaf;
    -- 4 = mega-entry sliding window (PALMA, MAHON, MALLORCA, …).
    window_size         INTEGER,
    -- Provenance.
    model               TEXT,                    -- e.g. 'claude-sonnet-4-6'
    source_file         TEXT,                    -- 'data/text/page_<vol>_<leaf>.json'
    extracted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_text_entries_vol_leaf
    ON text_entries(vol, leaf);
CREATE INDEX IF NOT EXISTS idx_text_entries_title
    ON text_entries(title);
CREATE INDEX IF NOT EXISTS idx_text_entries_island
    ON text_entries(island);
CREATE INDEX IF NOT EXISTS idx_text_entries_municipality
    ON text_entries(municipality);
