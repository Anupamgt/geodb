"""
DDL definitions and database initialization functions.
"""

# ── Shard DDL (one per year DB) ──────────────────────────────────────────────

SHARD_TABLES = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    file_type   TEXT NOT NULL CHECK(file_type IN ('kml', 'kmz', 'tif', 'tiff')),
    blob        BLOB,
    file_path   TEXT,
    hash_sha256 TEXT UNIQUE NOT NULL,
    size_bytes  INTEGER NOT NULL,
    ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metadata (
    file_id         INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    bbox_minx       REAL,
    bbox_miny       REAL,
    bbox_maxx       REAL,
    bbox_maxy       REAL,
    crs_epsg        INTEGER,
    band_count      INTEGER,
    resolution_x    REAL,
    resolution_y    REAL,
    width           INTEGER,
    height          INTEGER,
    nodata_value    REAL,
    bit_depth       INTEGER,
    compression     TEXT,
    data_type       TEXT,
    feature_count   INTEGER,
    layer_names     TEXT,
    geometry_types  TEXT,
    temporal_start  DATETIME,
    temporal_end    DATETIME,
    description     TEXT,
    tags            TEXT,
    source          TEXT,
    custom_props    TEXT
);

CREATE TABLE IF NOT EXISTS file_tags (
    file_id  INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (file_id, tag)
);

CREATE TABLE IF NOT EXISTS file_geometry_types (
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    geometry_type TEXT NOT NULL,
    count         INTEGER DEFAULT 0,
    PRIMARY KEY (file_id, geometry_type)
);
"""

SHARD_BTREE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_files_type      ON files(file_type);
CREATE INDEX IF NOT EXISTS idx_files_hash      ON files(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_files_ingested  ON files(ingested_at);
CREATE INDEX IF NOT EXISTS idx_meta_crs        ON metadata(crs_epsg);
CREATE INDEX IF NOT EXISTS idx_meta_bands      ON metadata(band_count);
CREATE INDEX IF NOT EXISTS idx_meta_res        ON metadata(resolution_x);
CREATE INDEX IF NOT EXISTS idx_meta_temporal   ON metadata(temporal_start, temporal_end);
CREATE INDEX IF NOT EXISTS idx_tags_tag        ON file_tags(tag);
CREATE INDEX IF NOT EXISTS idx_geomtype        ON file_geometry_types(geometry_type);
"""

SHARD_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS metadata_fts USING fts5(
    filename,
    description,
    tags,
    layer_names,
    source,
    content='',
    tokenize='porter unicode61'
);
"""

SHARD_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_metadata_fts_insert
AFTER INSERT ON metadata
BEGIN
    INSERT INTO metadata_fts(rowid, filename, description, tags, layer_names, source)
    SELECT NEW.file_id, f.filename, NEW.description, NEW.tags, NEW.layer_names, NEW.source
    FROM files f WHERE f.id = NEW.file_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_metadata_fts_delete
AFTER DELETE ON metadata
BEGIN
    INSERT INTO metadata_fts(metadata_fts, rowid, filename, description, tags, layer_names, source)
    VALUES('delete', OLD.file_id,
           (SELECT filename FROM files WHERE id = OLD.file_id),
           OLD.description, OLD.tags, OLD.layer_names, OLD.source);
END;

CREATE TRIGGER IF NOT EXISTS trg_metadata_fts_update
AFTER UPDATE ON metadata
BEGIN
    INSERT INTO metadata_fts(metadata_fts, rowid, filename, description, tags, layer_names, source)
    VALUES('delete', OLD.file_id,
           (SELECT filename FROM files WHERE id = OLD.file_id),
           OLD.description, OLD.tags, OLD.layer_names, OLD.source);
    INSERT INTO metadata_fts(rowid, filename, description, tags, layer_names, source)
    SELECT NEW.file_id, f.filename, NEW.description, NEW.tags, NEW.layer_names, NEW.source
    FROM files f WHERE f.id = NEW.file_id;
END;
"""

# ── Catalog DDL (master index) ───────────────────────────────────────────────

CATALOG_TABLES = """
CREATE TABLE IF NOT EXISTS shards (
    year        INTEGER PRIMARY KEY,
    db_path     TEXT NOT NULL,
    file_count  INTEGER DEFAULT 0,
    size_bytes  INTEGER DEFAULT 0,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_index (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id        INTEGER NOT NULL,
    year           INTEGER NOT NULL,
    filename       TEXT NOT NULL,
    file_type      TEXT NOT NULL,
    bbox_minx      REAL,
    bbox_miny      REAL,
    bbox_maxx      REAL,
    bbox_maxy      REAL,
    temporal_start DATETIME,
    temporal_end   DATETIME,
    tags           TEXT,
    UNIQUE(year, file_id)
);
"""

CATALOG_RTREE = """
CREATE VIRTUAL TABLE IF NOT EXISTS idx_file_bbox USING rtree(
    id,
    minx, maxx,
    miny, maxy
);
"""

CATALOG_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS catalog_fts USING fts5(
    filename,
    tags,
    content='',
    tokenize='porter unicode61'
);
"""

CATALOG_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_catalog_type     ON file_index(file_type);
CREATE INDEX IF NOT EXISTS idx_catalog_year     ON file_index(year);
CREATE INDEX IF NOT EXISTS idx_catalog_temporal ON file_index(temporal_start, temporal_end);
"""


# ── Init Functions ───────────────────────────────────────────────────────────

def _rtree_available(conn) -> bool:
    """Check whether SQLite was built with the rtree module."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _rtree_probe "
            "USING rtree(id, minx, maxx, miny, maxy)"
        )
        conn.execute("DROP TABLE _rtree_probe")
        return True
    except Exception:
        return False


def init_shard(conn, use_spatialite=True):
    """Initialize a year-shard database. Idempotent."""
    cur = conn.cursor()
    cur.executescript(SHARD_TABLES)
    cur.executescript(SHARD_BTREE_INDEXES)
    cur.executescript(SHARD_FTS)
    cur.executescript(SHARD_FTS_TRIGGERS)

    if use_spatialite:
        has_rtree = _rtree_available(conn)

        # Check if spatial metadata already initialized
        try:
            cur.execute("SELECT * FROM geometry_columns LIMIT 1")
        except Exception:
            cur.execute("SELECT InitSpatialMetaData(1)")

        # Add geometry column if not present
        geom_exists = True
        try:
            cur.execute("SELECT geometry FROM metadata LIMIT 1")
        except Exception:
            geom_exists = False
            cur.execute(
                "SELECT AddGeometryColumn('metadata', 'geometry', 4326, 'GEOMETRY', 'XY')"
            )
            if has_rtree:
                cur.execute("SELECT CreateSpatialIndex('metadata', 'geometry')")

        # Heal a previously-broken state: if SpatiaLite's metadata claims a
        # spatial index is enabled on metadata.geometry but the rtree-backed
        # idx_metadata_geometry table doesn't actually exist (because rtree
        # was unavailable when CreateSpatialIndex first ran), disable it so
        # INSERTs/UPDATEs stop tripping the missing-table error.
        if geom_exists:
            try:
                row = cur.execute(
                    "SELECT spatial_index_enabled FROM geometry_columns "
                    "WHERE f_table_name='metadata' AND f_geometry_column='geometry'"
                ).fetchone()
                index_flagged = bool(row and row[0])
            except Exception:
                index_flagged = False

            if index_flagged:
                idx_missing = False
                try:
                    cur.execute("SELECT 1 FROM idx_metadata_geometry LIMIT 1")
                except Exception:
                    idx_missing = True
                if idx_missing:
                    try:
                        cur.execute(
                            "SELECT DisableSpatialIndex('metadata', 'geometry')"
                        )
                    except Exception:
                        pass

    conn.commit()


def init_catalog(conn):
    """Initialize the catalog database. Idempotent."""
    cur = conn.cursor()
    cur.executescript(CATALOG_TABLES)
    cur.executescript(CATALOG_INDEXES)
    cur.executescript(CATALOG_FTS)

    # R-tree must be created via single statement (not executescript).
    # If the host SQLite lacks the rtree module this is a no-op; the reader
    # is responsible for falling back to file_index bbox columns.
    rtree_ok = False
    try:
        cur.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS idx_file_bbox USING rtree("
            "id, minx, maxx, miny, maxy)"
        )
        rtree_ok = True
    except Exception:
        pass

    # Backfill the rtree from file_index if it was just created (or was
    # populated under a previous broken state where rtree inserts silently
    # no-op'd in the writer).
    if rtree_ok:
        rtree_count = cur.execute(
            "SELECT COUNT(*) FROM idx_file_bbox"
        ).fetchone()[0]
        idx_count = cur.execute(
            "SELECT COUNT(*) FROM file_index WHERE bbox_minx IS NOT NULL"
        ).fetchone()[0]
        if rtree_count < idx_count:
            cur.execute(
                "INSERT INTO idx_file_bbox(id, minx, maxx, miny, maxy) "
                "SELECT id, bbox_minx, bbox_maxx, bbox_miny, bbox_maxy "
                "FROM file_index "
                "WHERE bbox_minx IS NOT NULL "
                "  AND id NOT IN (SELECT id FROM idx_file_bbox)"
            )

    conn.commit()
