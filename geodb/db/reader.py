"""
Query API: spatial search, full-text search, filter search, cross-shard queries.
"""
import json
import sqlite3


class ShardReader:
    """Queries a single year-shard database."""

    def __init__(self, conn, use_spatialite=True):
        self.conn = conn
        self.use_spatialite = use_spatialite

    def _query(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def search_spatial(self, minx, miny, maxx, maxy):
        """R-tree bbox intersection."""
        if self.use_spatialite:
            return self._query("""
                SELECT f.id, f.filename, f.file_type, m.*
                FROM metadata m
                JOIN files f ON f.id = m.file_id
                WHERE m.file_id IN (
                    SELECT rowid FROM SpatialIndex
                    WHERE f_table_name = 'metadata'
                      AND f_geometry_column = 'geometry'
                      AND search_frame = BuildMbr(?, ?, ?, ?, 4326)
                )
            """, (minx, miny, maxx, maxy))
        else:
            # Fallback: plain bbox comparison
            return self._query("""
                SELECT f.id, f.filename, f.file_type, m.*
                FROM metadata m
                JOIN files f ON f.id = m.file_id
                WHERE m.bbox_maxx >= ? AND m.bbox_minx <= ?
                  AND m.bbox_maxy >= ? AND m.bbox_miny <= ?
            """, (minx, maxx, miny, maxy))

    def search_text(self, query):
        """FTS5 ranked full-text search."""
        return self._query("""
            SELECT f.id, f.filename, f.file_type,
                   metadata_fts.rank AS fts_rank
            FROM metadata_fts
            JOIN files f ON f.id = metadata_fts.rowid
            WHERE metadata_fts MATCH ?
            ORDER BY metadata_fts.rank
        """, (query,))

    def search_filters(self, *, file_type=None, crs=None,
                       min_res=None, max_res=None,
                       bands=None, tags=None,
                       sensor=None, cloud_cover_max=None,
                       geometry_type=None,
                       temporal_start=None, temporal_end=None):
        """Dynamic attribute filter query."""
        clauses, params = [], []

        if file_type:
            clauses.append("f.file_type = ?")
            params.append(file_type)
        if crs:
            clauses.append("m.crs_epsg = ?")
            params.append(crs)
        if min_res is not None:
            clauses.append("m.resolution_x >= ?")
            params.append(min_res)
        if max_res is not None:
            clauses.append("m.resolution_x <= ?")
            params.append(max_res)
        if bands:
            clauses.append("m.band_count = ?")
            params.append(bands)
        if sensor:
            clauses.append("json_extract(m.custom_props, '$.sensor') = ?")
            params.append(sensor)
        if cloud_cover_max is not None:
            clauses.append(
                "CAST(json_extract(m.custom_props, '$.cloud_cover') AS REAL) <= ?"
            )
            params.append(cloud_cover_max)
        if geometry_type:
            clauses.append(
                "f.id IN (SELECT file_id FROM file_geometry_types "
                "WHERE geometry_type = ?)"
            )
            params.append(geometry_type)
        if tags:
            placeholders = ",".join("?" * len(tags))
            clauses.append(
                f"f.id IN (SELECT file_id FROM file_tags "
                f"WHERE tag IN ({placeholders}) "
                f"GROUP BY file_id HAVING COUNT(*) = ?)"
            )
            params.extend([t.lower() for t in tags])
            params.append(len(tags))
        if temporal_start:
            clauses.append("m.temporal_end >= ?")
            params.append(temporal_start)
        if temporal_end:
            clauses.append("m.temporal_start <= ?")
            params.append(temporal_end)

        where = " AND ".join(clauses) if clauses else "1=1"
        return self._query(f"""
            SELECT f.id, f.filename, f.file_type, m.*
            FROM files f
            JOIN metadata m ON f.id = m.file_id
            WHERE {where}
        """, params)

    def search_combined(self, *, bbox=None, text=None, **filters):
        """Intersect results from spatial, text, and filter searches."""
        result_sets = []

        if bbox:
            ids = {r["id"] for r in self.search_spatial(*bbox)}
            result_sets.append(ids)
        if text:
            ids = {r["id"] for r in self.search_text(text)}
            result_sets.append(ids)
        if filters:
            ids = {r["id"] for r in self.search_filters(**filters)}
            result_sets.append(ids)

        if not result_sets:
            return self._query(
                "SELECT f.id, f.filename, f.file_type, m.* "
                "FROM files f JOIN metadata m ON f.id = m.file_id"
            )

        final_ids = result_sets[0]
        for s in result_sets[1:]:
            final_ids &= s

        if not final_ids:
            return []

        placeholders = ",".join("?" * len(final_ids))
        return self._query(
            f"SELECT f.id, f.filename, f.file_type, m.* "
            f"FROM files f JOIN metadata m ON f.id = m.file_id "
            f"WHERE f.id IN ({placeholders})",
            list(final_ids),
        )

    def get_metadata(self, file_id):
        rows = self._query(
            "SELECT f.*, m.* FROM files f "
            "JOIN metadata m ON f.id = m.file_id WHERE f.id = ?",
            (file_id,),
        )
        return rows[0] if rows else None

    def get_blob(self, file_id):
        row = self.conn.execute(
            "SELECT blob, file_path FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if not row:
            return None
        if row["blob"]:
            return bytes(row["blob"])
        if row["file_path"]:
            with open(row["file_path"], "rb") as f:
                return f.read()
        return None

    def list_tags(self):
        return [
            r["tag"] for r in
            self._query("SELECT DISTINCT tag FROM file_tags ORDER BY tag")
        ]


class CatalogReader:
    """Queries the catalog to narrow shard selection."""

    def __init__(self, catalog_conn):
        self.conn = catalog_conn

    def _query(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def find_shards(self, *, bbox=None, temporal_start=None,
                    temporal_end=None, text=None, year=None):
        """Determine which year-shards to query."""
        if year is not None:
            return [year] if isinstance(year, int) else list(year)

        year_sets = []

        if bbox:
            minx, miny, maxx, maxy = bbox
            try:
                rows = self._query("""
                    SELECT DISTINCT fi.year
                    FROM idx_file_bbox r
                    JOIN file_index fi ON fi.id = r.id
                    WHERE r.maxx >= ? AND r.minx <= ?
                      AND r.maxy >= ? AND r.miny <= ?
                """, (minx, maxx, miny, maxy))
            except sqlite3.OperationalError:
                # rtree table missing — fall back to plain bbox scan
                rows = self._query("""
                    SELECT DISTINCT year
                    FROM file_index
                    WHERE bbox_maxx >= ? AND bbox_minx <= ?
                      AND bbox_maxy >= ? AND bbox_miny <= ?
                """, (minx, maxx, miny, maxy))
            year_sets.append({r["year"] for r in rows})

        if text:
            # Catalog FTS only indexes filename+tags; shard FTS indexes
            # description too. So treat this as a soft hint — if no catalog
            # matches, don't constrain shards (let shard-level FTS decide).
            rows = self._query("""
                SELECT DISTINCT fi.year
                FROM catalog_fts
                JOIN file_index fi ON fi.id = catalog_fts.rowid
                WHERE catalog_fts MATCH ?
            """, (text,))
            text_years = {r["year"] for r in rows}
            if text_years:  # Only constrain if catalog had matches
                year_sets.append(text_years)

        if temporal_start or temporal_end:
            clauses, params = [], []
            if temporal_start:
                clauses.append("temporal_end >= ?")
                params.append(temporal_start)
            if temporal_end:
                clauses.append("temporal_start <= ?")
                params.append(temporal_end)
            rows = self._query(
                f"SELECT DISTINCT year FROM file_index "
                f"WHERE {' AND '.join(clauses)}",
                params,
            )
            year_sets.append({r["year"] for r in rows})

        if not year_sets:
            return self.all_years()

        # Intersect all constraints
        result = year_sets[0]
        for s in year_sets[1:]:
            result &= s
        return sorted(result)

    def all_years(self):
        rows = self._query("SELECT year FROM shards ORDER BY year")
        return [r["year"] for r in rows]

    def shard_stats(self):
        return self._query(
            "SELECT year, file_count, size_bytes, created_at FROM shards ORDER BY year"
        )

    def search_quick(self, *, text=None, file_type=None, year=None):
        """Quick catalog-level search without opening shards."""
        clauses, params = [], []
        if text:
            clauses.append(
                "fi.id IN (SELECT rowid FROM catalog_fts WHERE catalog_fts MATCH ?)"
            )
            params.append(text)
        if file_type:
            clauses.append("fi.file_type = ?")
            params.append(file_type)
        if year:
            clauses.append("fi.year = ?")
            params.append(year)

        where = " AND ".join(clauses) if clauses else "1=1"
        return self._query(
            f"SELECT * FROM file_index fi WHERE {where} LIMIT 100", params
        )

    def list_all_tags(self):
        """Aggregate tags from catalog (JSON arrays)."""
        rows = self._query("SELECT tags FROM file_index WHERE tags IS NOT NULL")
        all_tags = set()
        for r in rows:
            try:
                all_tags.update(json.loads(r["tags"]))
            except Exception:
                pass
        return sorted(all_tags)
