"""
Data Extractor — extracts plottable geographic data from step output files.
Detects GeoJSON features, CSV with lat/lon, and TIF bounds.
Returns a unified format the map generator can consume.
"""
import csv
import json
import os


def extract_from_outputs(output_paths: dict) -> dict:
    """
    Scan step output files for plottable data.

    Args:
        output_paths: {filename: full_path}

    Returns:
        {
            has_data: bool,
            points: [{lat, lon, label, value}],
            polygons: [{coords: [[lon,lat],...], label, properties}],
            lines: [{coords: [[lon,lat],...], label}],
            bounds: [min_lon, min_lat, max_lon, max_lat],
            summary: "short description of what was found",
        }
    """
    result = {
        "has_data": False,
        "points": [],
        "polygons": [],
        "lines": [],
        "bounds": None,
        "summary": "",
    }

    for fname, fpath in output_paths.items():
        if not os.path.isfile(fpath):
            continue

        ext = os.path.splitext(fname)[1].lower()

        try:
            if ext == ".geojson" or ext == ".json":
                _extract_geojson(fpath, result)
            elif ext == ".csv":
                _extract_csv(fpath, result)
            elif ext in (".tif", ".tiff"):
                _extract_tif_bounds(fpath, result)
        except Exception:
            pass

    # Compute bounds from all data
    all_coords = []
    for p in result["points"]:
        all_coords.append((p["lon"], p["lat"]))
    for poly in result["polygons"]:
        all_coords.extend(poly["coords"])
    for line in result["lines"]:
        all_coords.extend(line["coords"])

    if all_coords:
        lons = [c[0] for c in all_coords]
        lats = [c[1] for c in all_coords]
        result["bounds"] = [min(lons), min(lats), max(lons), max(lats)]
        result["has_data"] = True

    # Summary
    parts = []
    if result["points"]:
        parts.append(f"{len(result['points'])} points")
    if result["polygons"]:
        parts.append(f"{len(result['polygons'])} polygons")
    if result["lines"]:
        parts.append(f"{len(result['lines'])} lines")
    result["summary"] = ", ".join(parts) if parts else "no geo data"

    return result


def _extract_geojson(path, result):
    with open(path) as f:
        data = json.load(f)

    features = data.get("features", [])
    if not features and data.get("type") == "Feature":
        features = [data]
    if not features and data.get("geometry"):
        features = [{"type": "Feature", "geometry": data, "properties": {}}]

    for feat in features:
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})
        label = props.get("name", props.get("Name", props.get("id", "")))
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])

        if gtype == "Point" and coords:
            result["points"].append({
                "lon": coords[0], "lat": coords[1],
                "label": str(label),
                "value": props.get("height_m", props.get("elevation", props.get("value", ""))),
            })

        elif gtype == "Polygon" and coords:
            ring = [[c[0], c[1]] for c in coords[0]]
            result["polygons"].append({"coords": ring, "label": str(label), "properties": props})

        elif gtype == "MultiPolygon" and coords:
            for poly in coords:
                ring = [[c[0], c[1]] for c in poly[0]]
                result["polygons"].append({"coords": ring, "label": str(label), "properties": props})

        elif gtype == "LineString" and coords:
            line = [[c[0], c[1]] for c in coords]
            result["lines"].append({"coords": line, "label": str(label)})

        elif gtype == "MultiLineString" and coords:
            for linecoords in coords:
                line = [[c[0], c[1]] for c in linecoords]
                result["lines"].append({"coords": line, "label": str(label)})


def _extract_csv(path, result):
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Detect lat/lon columns
        lat_col = None
        lon_col = None
        for h in headers:
            hl = h.lower().strip()
            if hl in ("lat", "latitude", "y", "lat_y", "lat_dd"):
                lat_col = h
            elif hl in ("lon", "lng", "longitude", "x", "lon_x", "lon_dd"):
                lon_col = h

        if not lat_col or not lon_col:
            return

        # Detect value column
        value_col = None
        for h in headers:
            hl = h.lower()
            if any(k in hl for k in ("height", "elev", "alt", "value", "z", "slope", "temp")):
                value_col = h
                break

        # Detect label column
        label_col = None
        for h in headers:
            hl = h.lower()
            if any(k in hl for k in ("id", "point", "name", "label", "index")):
                label_col = h
                break

        for row in reader:
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
                if abs(lat) > 90 or abs(lon) > 180:
                    continue
                pt = {"lat": lat, "lon": lon, "label": "", "value": ""}
                if label_col and row.get(label_col):
                    pt["label"] = str(row[label_col])
                if value_col and row.get(value_col):
                    pt["value"] = str(row[value_col])
                result["points"].append(pt)
            except (ValueError, TypeError, KeyError):
                pass


def _extract_tif_bounds(path, result):
    """Extract raster bounds as a polygon outline."""
    try:
        import rasterio
        with rasterio.open(path) as ds:
            b = ds.bounds
            ring = [
                [b.left, b.bottom], [b.right, b.bottom],
                [b.right, b.top], [b.left, b.top],
                [b.left, b.bottom],
            ]
            result["polygons"].append({
                "coords": ring,
                "label": os.path.basename(path),
                "properties": {"type": "raster_bounds"},
            })
    except Exception:
        pass
