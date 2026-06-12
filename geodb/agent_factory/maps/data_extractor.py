"""
Data Extractor — finds plottable geospatial data in step output files.
Returns a standardized dict of GeoJSON features ready for the map template.
"""
import csv
import json
import os


def extract_map_data(output_paths: dict) -> dict:
    """
    Scan step output files and extract anything plottable.

    Args:
        output_paths: {filename: full_path}

    Returns: {
        "features": [GeoJSON Feature dicts],
        "bounds": [minlon, minlat, maxlon, maxlat] or None,
        "summary": "human-readable summary",
        "has_data": bool,
    }
    """
    all_features = []
    all_coords = []

    for fname, fpath in output_paths.items():
        if not os.path.isfile(fpath):
            continue

        ext = os.path.splitext(fname)[1].lower()

        try:
            if ext == ".geojson":
                feats, coords = _from_geojson(fpath)
                all_features.extend(feats)
                all_coords.extend(coords)

            elif ext == ".csv":
                feats, coords = _from_csv(fpath)
                all_features.extend(feats)
                all_coords.extend(coords)

            elif ext in (".xlsx", ".xls"):
                feats, coords = _from_excel(fpath)
                all_features.extend(feats)
                all_coords.extend(coords)

            elif ext in (".tif", ".tiff"):
                feats, coords = _from_tif_bounds(fpath)
                all_features.extend(feats)
                all_coords.extend(coords)

            elif ext == ".kml":
                feats, coords = _from_kml(fpath)
                all_features.extend(feats)
                all_coords.extend(coords)

        except Exception:
            pass

    bounds = None
    if all_coords:
        lons = [c[0] for c in all_coords]
        lats = [c[1] for c in all_coords]
        bounds = [min(lons), min(lats), max(lons), max(lats)]

    summary_parts = []
    points = [f for f in all_features if f["geometry"]["type"] == "Point"]
    polys = [f for f in all_features if f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
    lines = [f for f in all_features if f["geometry"]["type"] in ("LineString", "MultiLineString")]
    if points:
        summary_parts.append(f"{len(points)} points")
    if polys:
        summary_parts.append(f"{len(polys)} polygons")
    if lines:
        summary_parts.append(f"{len(lines)} lines")

    return {
        "features": all_features,
        "bounds": bounds,
        "summary": ", ".join(summary_parts) if summary_parts else "no spatial data",
        "has_data": len(all_features) > 0,
    }


def _from_geojson(path):
    with open(path) as f:
        data = json.load(f)

    features = data.get("features", [])
    if not features and data.get("type") == "Feature":
        features = [data]
    elif not features and data.get("geometry"):
        features = [{"type": "Feature", "geometry": data, "properties": {}}]

    coords = []
    for feat in features:
        _collect_coords(feat.get("geometry", {}), coords)

    return features, coords


def _from_csv(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Find lat/lon columns
        lat_col = _find_col(headers, ["lat", "latitude", "y", "lat_y", "lat_dd"])
        lon_col = _find_col(headers, ["lon", "lng", "longitude", "x", "lon_x", "lon_dd"])

        if not lat_col or not lon_col:
            return [], []

        features = []
        coords = []
        for row in reader:
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
                # Basic validity check
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    props = {k: v for k, v in row.items() if k not in (lat_col, lon_col)}
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": props,
                    })
                    coords.append((lon, lat))
            except (ValueError, TypeError, KeyError):
                pass

    return features, coords


def _from_excel(path):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        if not rows:
            return [], []

        headers = [str(c) if c else f"col_{i}" for i, c in enumerate(rows[0])]
        lat_col = _find_col(headers, ["lat", "latitude", "y"])
        lon_col = _find_col(headers, ["lon", "lng", "longitude", "x"])

        if not lat_col or not lon_col:
            return [], []

        li = headers.index(lat_col)
        lo = headers.index(lon_col)

        features = []
        coords = []
        for row in rows[1:]:
            try:
                lat = float(row[li])
                lon = float(row[lo])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    props = {headers[i]: row[i] for i in range(len(headers))
                             if i not in (li, lo) and i < len(row)}
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {k: str(v) for k, v in props.items()},
                    })
                    coords.append((lon, lat))
            except (ValueError, TypeError, IndexError):
                pass

        return features, coords
    except Exception:
        return [], []


def _from_tif_bounds(path):
    """Extract raster bounding box as a polygon feature."""
    try:
        import rasterio
        with rasterio.open(path) as ds:
            b = ds.bounds
            polygon = {
                "type": "Polygon",
                "coordinates": [[
                    [b.left, b.bottom], [b.right, b.bottom],
                    [b.right, b.top], [b.left, b.top],
                    [b.left, b.bottom],
                ]],
            }
            feat = {
                "type": "Feature",
                "geometry": polygon,
                "properties": {
                    "type": "raster_extent",
                    "bands": ds.count,
                    "crs": str(ds.crs),
                },
            }
            corners = [(b.left, b.bottom), (b.right, b.bottom),
                       (b.right, b.top), (b.left, b.top)]
            return [feat], corners
    except Exception:
        return [], []


def _from_kml(path):
    from lxml import etree
    ns = "{http://www.opengis.net/kml/2.2}"
    tree = etree.parse(path, etree.XMLParser(recover=True))
    root = tree.getroot()

    features = []
    coords = []

    for pm in root.iter(f"{ns}Placemark"):
        coords_el = pm.find(f".//{ns}coordinates")
        if coords_el is None or not coords_el.text:
            continue

        ring = []
        for t in coords_el.text.strip().split():
            parts = t.split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = float(parts[0]), float(parts[1])
                    ring.append([lon, lat])
                    coords.append((lon, lat))
                except ValueError:
                    pass

        if not ring:
            continue

        name_el = pm.find(f"{ns}name")
        name = name_el.text.strip() if name_el is not None and name_el.text else ""

        if pm.find(f".//{ns}Polygon") is not None and len(ring) >= 3:
            geom = {"type": "Polygon", "coordinates": [ring]}
        elif pm.find(f".//{ns}LineString") is not None and len(ring) >= 2:
            geom = {"type": "LineString", "coordinates": ring}
        elif len(ring) == 1:
            geom = {"type": "Point", "coordinates": ring[0]}
        else:
            geom = {"type": "LineString", "coordinates": ring}

        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {"name": name},
        })

    return features, coords


def _find_col(headers, candidates):
    for h in headers:
        if h.lower().strip() in candidates:
            return h
    return None


def _collect_coords(geom, out):
    gtype = geom.get("type", "")
    c = geom.get("coordinates")
    if gtype == "Point" and c:
        out.append(tuple(c[:2]))
    elif gtype in ("LineString", "MultiPoint") and c:
        for pt in c:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                out.append(tuple(pt[:2]))
    elif gtype in ("Polygon", "MultiLineString") and c:
        for ring in c:
            for pt in ring:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    out.append(tuple(pt[:2]))
    elif gtype == "MultiPolygon" and c:
        for poly in c:
            for ring in poly:
                for pt in ring:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        out.append(tuple(pt[:2]))
