"""
Shard connection manager with SpatiaLite support and connection caching.
"""
import os
import sqlite3
from geodb.config import (
    DATA_DIR, CATALOG_DB_PATH, SHARD_PRAGMAS, PAGE_SIZE,
    SPATIALITE_EXT, shard_db_path,
)
from geodb.schema import init_shard, init_catalog


class ShardManager:
    """Manages connections to year-sharded databases and the catalog."""

    def __init__(self, use_spatialite=True):
        self.use_spatialite = use_spatialite
        self._shards = {}       # year -> connection
        self._catalog = None
        os.makedirs(DATA_DIR, exist_ok=True)

    def _apply_pragmas(self, conn, is_new=False):
        cur = conn.cursor()
        if is_new:
            cur.execute(f"PRAGMA page_size={PAGE_SIZE}")
        for key, val in SHARD_PRAGMAS.items():
            cur.execute(f"PRAGMA {key}={val}")

    def _load_spatialite(self, conn):
        if not self.use_spatialite:
            return
        conn.enable_load_extension(True)
        try:
            conn.load_extension(SPATIALITE_EXT)
        except Exception as e:
            print(f"[WARN] SpatiaLite not loaded: {e}. Spatial queries disabled.")
            self.use_spatialite = False

    def _connect(self, db_path, is_new=False):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        self._apply_pragmas(conn, is_new=is_new)
        self._load_spatialite(conn)
        return conn

    def get_shard(self, year: int):
        """Get or create a shard connection for the given year."""
        if year in self._shards:
            return self._shards[year]

        db_path = shard_db_path(year)
        is_new = not os.path.exists(db_path)
        conn = self._connect(db_path, is_new=is_new)
        init_shard(conn, use_spatialite=self.use_spatialite)

        # Register shard in catalog
        cat = self.get_catalog()
        cat.execute(
            "INSERT OR IGNORE INTO shards(year, db_path) VALUES(?, ?)",
            (year, db_path),
        )
        cat.commit()

        self._shards[year] = conn
        return conn

    def get_catalog(self):
        """Get or create the catalog connection."""
        if self._catalog is not None:
            return self._catalog

        is_new = not os.path.exists(CATALOG_DB_PATH)
        self._catalog = sqlite3.connect(CATALOG_DB_PATH)
        self._catalog.row_factory = sqlite3.Row
        self._catalog.execute("PRAGMA foreign_keys=ON")
        self._apply_pragmas(self._catalog, is_new=is_new)
        init_catalog(self._catalog)
        return self._catalog

    def all_years(self):
        """Return all registered shard years."""
        cat = self.get_catalog()
        rows = cat.execute("SELECT year FROM shards ORDER BY year").fetchall()
        return [r["year"] for r in rows]

    def close(self):
        for conn in self._shards.values():
            conn.close()
        self._shards.clear()
        if self._catalog:
            self._catalog.close()
            self._catalog = None
