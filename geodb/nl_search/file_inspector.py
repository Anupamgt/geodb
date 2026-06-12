"""
File-content inspector.

Lets the NL pipeline answer questions about the *contents* of a referenced
file (placemarks, coordinates, layers, raster bands, etc.) — not just the
SQL-indexed metadata. Reads the file from `file_path` if present, otherwise
falls back to the `blob` column.
"""
from __future__ import annotations
import json
import os
import tempfile
from typing import Optional
from lxml import etree


KML_NS = "{http://www.opengis.net/kml/2.2}"

# Heuristics: which user queries actually need file contents (not just metadata)
_CONTENT_KEYWORDS = (
    "placemark", "placemarks", "coordinates", "coords", "points", "vertices",
    "what's in", "whats in", "what is in", "contents", "content of",
    "show me the data", "inside", "features in", "list features",
    "list layers", "layer names", "folder", "folders",
    "bands", "band count", "resolution", "pixel", "width", "height",
    "extended data", "attributes of", "properties of",
    "polygon", "polygons", "line", "lines", "name of", "names in",
)


def needs_inspection(user_query: str) -> bool:
    q = user_query.lower()
    return any(k in q for k in _CONTENT_KEYWORDS)


def _resolve_path(row: dict) -> Optional[str]:
    """Return a usable filesystem path for the row, materializing the blob if needed."""
    p = row.get("file_path")
    if p and os.path.isfile(p):
        return p

    blob = row.get("blob")
    if blob:
        suffix = ".kml" if (row.get("file_type") == "kml") else ".tif"
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        return tmp
    return None


def inspect(row: dict, max_items: int = 20) -> Optional[dict]:
    """
    Inspect one result row and return a content summary, or None if not possible.
    """
    ftype = (row.get("file_type") or "").lower()
    path = _resolve_path(row)
    if not path:
        return {"error": "file not accessible (no file_path and no blob)"}

    try:
        if ftype == "kml":
            return _inspect_kml(path, max_items)
        if ftype == "tif":
            return _inspect_tif(path)
    except Exception as e:
        return {"error": f"inspection failed: {e}"}
    return None


# ── KML ──────────────────────────────────────────────────────────────────────

def _inspect_kml(path: str, max_items: int) -> dict:
    try:
        tree = etree.parse(path)
    except etree.XMLSyntaxError:
        tree = etree.parse(path, parser=etree.XMLParser(recover=True))
    root = tree.getroot()
    ns = KML_NS

    placemarks = []
    for pm in root.iter(f"{ns}Placemark"):
        name_el = pm.find(f"{ns}name")
        desc_el = pm.find(f"{ns}description")
        geom_type = None
        for tag in ("Point", "LineString", "Polygon", "MultiGeometry", "LinearRing"):
            if pm.find(f".//{ns}{tag}") is not None:
                geom_type = tag
                break
        coords_el = pm.find(f".//{ns}coordinates")
        coord_count = 0
        first_coord = None
        if coords_el is not None and coords_el.text:
            triplets = coords_el.text.strip().split()
            coord_count = len(triplets)
            if triplets:
                parts = triplets[0].split(",")
                if len(parts) >= 2:
                    first_coord = (float(parts[0]), float(parts[1]))
        placemarks.append({
            "name": (name_el.text.strip() if name_el is not None and name_el.text else None),
            "description": (desc_el.text.strip()[:120] if desc_el is not None and desc_el.text else None),
            "geometry": geom_type,
            "coord_count": coord_count,
            "first_coord": first_coord,
        })
        if len(placemarks) >= max_items:
            break

    folders = []
    for folder in root.iter(f"{ns}Folder"):
        name_el = folder.find(f"{ns}name")
        if name_el is not None and name_el.text:
            folders.append(name_el.text.strip())

    total_placemarks = sum(1 for _ in root.iter(f"{ns}Placemark"))

    return {
        "kind": "kml",
        "total_placemarks": total_placemarks,
        "shown_placemarks": len(placemarks),
        "placemarks": placemarks,
        "folders": folders,
    }


# ── TIF ──────────────────────────────────────────────────────────────────────

def _inspect_tif(path: str) -> dict:
    import rasterio
    with rasterio.open(path) as ds:
        out = {
            "kind": "tif",
            "width": ds.width,
            "height": ds.height,
            "band_count": ds.count,
            "dtypes": list(ds.dtypes),
            "crs": str(ds.crs) if ds.crs else None,
            "bounds": list(ds.bounds),
            "resolution": list(ds.res),
            "nodata": ds.nodata,
            "tags": dict(ds.tags()) or None,
        }
        bands = []
        for i in range(1, ds.count + 1):
            band = {"index": i, "description": ds.descriptions[i - 1]}
            try:
                stats = ds.statistics(i, approx=True)
                band["min"] = stats.min
                band["max"] = stats.max
                band["mean"] = stats.mean
            except Exception:
                pass
            bands.append(band)
        out["bands"] = bands
    return out
