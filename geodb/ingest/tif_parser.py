"""
Parse GeoTIFF files and extract metadata using rasterio (GDAL).
Never loads pixel data into RAM.
"""
import json
import os
from datetime import datetime

import rasterio
from rasterio.crs import CRS


# Map numpy dtype to bit depth
DTYPE_BITS = {
    "uint8": 8, "int8": 8,
    "uint16": 16, "int16": 16,
    "uint32": 32, "int32": 32,
    "float32": 32, "float64": 64,
}


def parse(filepath: str) -> dict:
    """
    Parse a GeoTIFF and return a metadata dict.
    """
    meta = {
        "file_type": "tif",
        "feature_count": None,
        "geometry_types": None,
        "layer_names": None,
    }

    with rasterio.open(filepath) as ds:
        # ── CRS ───────────────────────────────────────────────────────
        epsg = None
        if ds.crs:
            try:
                epsg = ds.crs.to_epsg()
            except Exception:
                pass
        meta["crs_epsg"] = epsg or 4326

        # ── Bounding box ──────────────────────────────────────────────
        bounds = ds.bounds
        # If CRS is not 4326, reproject bounds
        if epsg and epsg != 4326 and ds.crs:
            try:
                from rasterio.warp import transform_bounds
                b = transform_bounds(ds.crs, CRS.from_epsg(4326),
                                     bounds.left, bounds.bottom,
                                     bounds.right, bounds.top)
                meta["bbox_minx"] = b[0]
                meta["bbox_miny"] = b[1]
                meta["bbox_maxx"] = b[2]
                meta["bbox_maxy"] = b[3]
            except Exception:
                meta["bbox_minx"] = bounds.left
                meta["bbox_miny"] = bounds.bottom
                meta["bbox_maxx"] = bounds.right
                meta["bbox_maxy"] = bounds.top
        else:
            meta["bbox_minx"] = bounds.left
            meta["bbox_miny"] = bounds.bottom
            meta["bbox_maxx"] = bounds.right
            meta["bbox_maxy"] = bounds.top

        # ── Raster properties ─────────────────────────────────────────
        meta["band_count"] = ds.count
        meta["resolution_x"] = abs(ds.res[0])
        meta["resolution_y"] = abs(ds.res[1])
        meta["width"] = ds.width
        meta["height"] = ds.height

        nodata = ds.nodata
        meta["nodata_value"] = float(nodata) if nodata is not None else None

        dtype = ds.dtypes[0] if ds.dtypes else None
        meta["data_type"] = str(dtype)
        meta["bit_depth"] = DTYPE_BITS.get(str(dtype))

        profile = ds.profile
        meta["compression"] = str(profile.get("compress", "none"))

        # ── GDAL metadata → description, temporal, custom ─────────────
        gdal_meta = ds.tags() or {}
        all_meta = dict(gdal_meta)
        # Also read per-domain metadata
        for domain in ["", "IMAGE_STRUCTURE", "DERIVED_SUBDATASETS"]:
            try:
                dm = ds.tags(ns=domain)
                if dm:
                    all_meta.update(dm)
            except Exception:
                pass

        meta["description"] = all_meta.get("TIFFTAG_IMAGEDESCRIPTION",
                               all_meta.get("description", None))

        # Temporal from metadata
        temporal_keys = [
            "TIFFTAG_DATETIME", "datetime", "date", "acquisition_date",
            "DATE_ACQUIRED", "SENSING_TIME",
        ]
        parsed_times = []
        for key in temporal_keys:
            val = all_meta.get(key)
            if not val:
                continue
            for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                         "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y"):
                try:
                    parsed_times.append(datetime.strptime(val, fmt))
                    break
                except ValueError:
                    continue

        if parsed_times:
            meta["temporal_start"] = min(parsed_times).isoformat()
            meta["temporal_end"] = max(parsed_times).isoformat()
        else:
            meta["temporal_start"] = None
            meta["temporal_end"] = None

        # Custom props (everything else interesting)
        skip_keys = {"TIFFTAG_IMAGEDESCRIPTION", "description"}
        skip_keys.update(k.lower() for k in temporal_keys)
        custom = {}
        for k, v in all_meta.items():
            if k.lower() not in skip_keys and v:
                custom[k] = v
        meta["custom_props"] = json.dumps(custom) if custom else None

        # ── Layer names (subdataset names) ────────────────────────────
        subdatasets = ds.subdatasets or []
        meta["layer_names"] = json.dumps(subdatasets) if subdatasets else None

    # ── Tags ──────────────────────────────────────────────────────────
    tags = ["tif"]
    if meta["band_count"]:
        tags.append(f"{meta['band_count']}-band")
    if meta.get("data_type"):
        tags.append(meta["data_type"])
    if meta.get("compression") and meta["compression"] != "none":
        tags.append(meta["compression"])
    meta["tags"] = json.dumps(list(set(tags)))

    # ── Source ─────────────────────────────────────────────────────────
    meta["source"] = os.path.basename(filepath)

    # ── Year ──────────────────────────────────────────────────────────
    if parsed_times:
        meta["year"] = min(parsed_times).year
    else:
        mtime = os.path.getmtime(filepath)
        meta["year"] = datetime.fromtimestamp(mtime).year

    return meta
