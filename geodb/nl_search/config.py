"""
Configuration for the Natural Language Search system.
Runs on top of the existing geodb database — never writes to it.
"""
import os

# ── Ollama / LLM ─────────────────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME = os.environ.get("GEODB_MODEL", "qwen2.5-coder:7b")
LLM_TIMEOUT = 60
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 2048

# ── Agent loop ────────────────────────────────────────────────────────────────
MAX_RETRIES = 3
SAFE_ROW_LIMIT = 200

# ── Paths ─────────────────────────────────────────────────────────────────────
DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)

# ── SQL safety ────────────────────────────────────────────────────────────────
BLOCKED_KEYWORDS = [
    "DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ",
    "CREATE ", "ATTACH ", "DETACH ", "PRAGMA ", "VACUUM",
    "REPLACE ", "GRANT ", "REVOKE ",
]

# ── Schema context (injected verbatim into every LLM prompt) ─────────────────
# Describes the ACTUAL tables present in every year-shard DB.
SCHEMA_CONTEXT = """\
-- DATABASE: SQLite (one .db per year, identical schema, queried independently)
-- SpatiaLite is loaded; spatial functions available.

CREATE TABLE files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,       -- e.g. 'DEM_demo.tif', 'Moga.kml', 'Natural Drain 1.kml'
    file_type   TEXT NOT NULL,       -- 'kml' or 'tif'
    blob        BLOB,               -- raw file bytes (may be NULL)
    file_path   TEXT,               -- original path on disk
    hash_sha256 TEXT UNIQUE NOT NULL,
    size_bytes  INTEGER NOT NULL,
    ingested_at DATETIME            -- DB insertion time, NOT the file's date. Do NOT use for year/date filtering.
);

CREATE TABLE metadata (
    file_id         INTEGER PRIMARY KEY REFERENCES files(id),
    bbox_minx       REAL,    -- longitude west   (e.g. 74.16)
    bbox_miny       REAL,    -- latitude south    (e.g. 30.58)
    bbox_maxx       REAL,    -- longitude east    (e.g. 76.53)
    bbox_maxy       REAL,    -- latitude north    (e.g. 31.28)
    crs_epsg        INTEGER, -- 4326 for KML
    band_count      INTEGER, -- raster bands (TIF only)
    resolution_x    REAL,    -- pixel size (TIF only)
    resolution_y    REAL,
    width           INTEGER, -- pixels (TIF only)
    height          INTEGER,
    nodata_value    REAL,
    bit_depth       INTEGER,
    compression     TEXT,
    data_type       TEXT,    -- 'uint8', 'float32' …
    feature_count   INTEGER, -- KML vector features
    layer_names     TEXT,    -- JSON array of folder/layer names
    geometry_types  TEXT,    -- JSON array e.g. '["Polygon","Point"]'
    temporal_start  DATETIME,        -- file's actual date (USE THIS for year/date filtering)
    temporal_end    DATETIME,        -- file's actual end date
    description     TEXT,    -- free text (often NULL for KMLs)
    tags            TEXT,    -- JSON array e.g. '["kml","polygon","Moga"]'
    source          TEXT,    -- original filename
    custom_props    TEXT     -- JSON object of extra properties
);

CREATE TABLE file_tags (
    file_id INTEGER REFERENCES files(id),
    tag     TEXT NOT NULL,
    PRIMARY KEY (file_id, tag)
);

CREATE TABLE file_geometry_types (
    file_id       INTEGER REFERENCES files(id),
    geometry_type TEXT NOT NULL,   -- 'Point','LineString','Polygon','LinearRing','MultiGeometry'
    count         INTEGER,
    PRIMARY KEY (file_id, geometry_type)
);

-- FTS5 full-text index:
--   metadata_fts(filename, description, tags, layer_names, source)
--   Usage: SELECT * FROM metadata_fts WHERE metadata_fts MATCH 'drain'

-- SPATIAL RULES:
-- Coordinates are WGS84 (EPSG:4326).  bbox values: minx/maxx = longitude, miny/maxy = latitude.
-- Most files in this DB are in Punjab, India (lon ≈ 74–77, lat ≈ 30–32).
-- Distance approximation at 30°N:
--     1 km ≈ 0.009° latitude
--     1 km ≈ 0.0104° longitude  (= 0.009 / cos(30°))
-- To find files near (lon, lat) within R km, use:
--     m.bbox_maxx >= lon - R*0.0104  AND  m.bbox_minx <= lon + R*0.0104
--     m.bbox_maxy >= lat - R*0.009   AND  m.bbox_miny <= lat + R*0.009
-- For filename-pattern search: f.filename LIKE '%keyword%'
-- Always: JOIN files f, metadata m ON f.id = m.file_id
-- Always: end with LIMIT
-- NEVER: DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, ATTACH
"""
