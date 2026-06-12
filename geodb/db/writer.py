"""
Writes parsed file data into the appropriate year shard and catalog.
"""
import json
import sqlite3


def ingest_file(data: dict, shard_conn, catalog_conn, use_spatialite=True) -> str:
    """
    Insert a single file into the shard and catalog.

    Args:
        data: dict from router.route()
        shard_conn: connection to the year shard DB
        catalog_conn: connection to catalog.db
        use_spatialite: whether spatial functions are available

    Returns:
        'inserted', 'skipped' (duplicate), or 'error:<msg>'
    """
    cur = shard_conn.cursor()
    cat = catalog_conn.cursor()

    try:
        # ── Dedup check ───────────────────────────────────────────────
        existing = cur.execute(
            "SELECT id FROM files WHERE hash_sha256 = ?",
            (data["hash_sha256"],)
        ).fetchone()
        if existing:
            return "skipped"

        # ── Insert into files ─────────────────────────────────────────
        cur.execute("""
            INSERT INTO files (filename, file_type, blob, file_path,
                               hash_sha256, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data["filename"],
            data["file_type"],
            data.get("blob"),
            data.get("filepath"),
            data["hash_sha256"],
            data["size_bytes"],
        ))
        file_id = cur.lastrowid

        # ── Insert into metadata ──────────────────────────────────────
        cur.execute("""
            INSERT INTO metadata (
                file_id, bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
                crs_epsg, band_count, resolution_x, resolution_y,
                width, height, nodata_value, bit_depth, compression,
                data_type, feature_count, layer_names, geometry_types,
                temporal_start, temporal_end, description, tags,
                source, custom_props
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            file_id,
            data.get("bbox_minx"), data.get("bbox_miny"),
            data.get("bbox_maxx"), data.get("bbox_maxy"),
            data.get("crs_epsg"), data.get("band_count"),
            data.get("resolution_x"), data.get("resolution_y"),
            data.get("width"), data.get("height"),
            data.get("nodata_value"), data.get("bit_depth"),
            data.get("compression"), data.get("data_type"),
            data.get("feature_count"), data.get("layer_names"),
            data.get("geometry_types"),
            data.get("temporal_start"), data.get("temporal_end"),
            data.get("description"), data.get("tags"),
            data.get("source"), data.get("custom_props"),
        ))

        # ── SpatiaLite geometry ───────────────────────────────────────
        if use_spatialite and data.get("bbox_minx") is not None:
            try:
                cur.execute("""
                    UPDATE metadata SET geometry = BuildMbr(?, ?, ?, ?, 4326)
                    WHERE file_id = ?
                """, (
                    data["bbox_minx"], data["bbox_miny"],
                    data["bbox_maxx"], data["bbox_maxy"],
                    file_id,
                ))
            except Exception:
                pass  # Spatial not available, skip

        # ── file_tags ─────────────────────────────────────────────────
        tags = data.get("tags")
        if tags:
            tag_list = json.loads(tags) if isinstance(tags, str) else tags
            for tag in tag_list:
                cur.execute(
                    "INSERT OR IGNORE INTO file_tags(file_id, tag) VALUES(?, ?)",
                    (file_id, tag.lower().strip()),
                )

        # ── file_geometry_types ───────────────────────────────────────
        geom_counts = data.get("geometry_type_counts", {})
        for gtype, count in geom_counts.items():
            cur.execute(
                "INSERT OR IGNORE INTO file_geometry_types(file_id, geometry_type, count) "
                "VALUES(?, ?, ?)",
                (file_id, gtype, count),
            )

        shard_conn.commit()

        # ── Catalog: file_index ───────────────────────────────────────
        cat.execute("""
            INSERT INTO file_index (
                file_id, year, filename, file_type,
                bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
                temporal_start, temporal_end, tags
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            file_id, data["year"], data["filename"], data["file_type"],
            data.get("bbox_minx"), data.get("bbox_miny"),
            data.get("bbox_maxx"), data.get("bbox_maxy"),
            data.get("temporal_start"), data.get("temporal_end"),
            data.get("tags"),
        ))
        catalog_rowid = cat.lastrowid

        # ── Catalog: R-tree ───────────────────────────────────────────
        if data.get("bbox_minx") is not None:
            try:
                cat.execute(
                    "INSERT INTO idx_file_bbox(id, minx, maxx, miny, maxy) "
                    "VALUES(?, ?, ?, ?, ?)",
                    (catalog_rowid,
                     data["bbox_minx"], data["bbox_maxx"],
                     data["bbox_miny"], data["bbox_maxy"]),
                )
            except sqlite3.OperationalError:
                pass  # rtree module not available; bbox cols on file_index still work

        # ── Catalog: FTS ──────────────────────────────────────────────
        cat.execute(
            "INSERT INTO catalog_fts(rowid, filename, tags) VALUES(?, ?, ?)",
            (catalog_rowid, data["filename"], data.get("tags", "")),
        )

        # ── Catalog: update shard stats ───────────────────────────────
        cat.execute(
            "UPDATE shards SET file_count = file_count + 1, "
            "size_bytes = size_bytes + ? WHERE year = ?",
            (data["size_bytes"], data["year"]),
        )

        catalog_conn.commit()
        return "inserted"

    except sqlite3.IntegrityError as e:
        shard_conn.rollback()
        catalog_conn.rollback()
        if "UNIQUE" in str(e):
            return "skipped"
        return f"error:{e}"
    except Exception as e:
        shard_conn.rollback()
        catalog_conn.rollback()
        return f"error:{e}"
