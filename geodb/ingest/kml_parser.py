"""
Parse KML/KMZ files and extract metadata without loading full geometry into RAM.
"""
import json
import os
import tempfile
import zipfile
from datetime import datetime
from lxml import etree


KML_NS = "{http://www.opengis.net/kml/2.2}"


def parse(filepath: str) -> dict:
    """Auto-detects KMZ and extracts the inner KML before parsing."""
    if filepath.lower().endswith(".kmz"):
        return _parse_kmz(filepath)
    return _parse_kml(filepath)


def _parse_kmz(filepath: str) -> dict:
    with zipfile.ZipFile(filepath, "r") as z:
        kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
        if not kml_names:
            raise ValueError("No KML found inside KMZ")
        with tempfile.TemporaryDirectory() as tmp:
            z.extract(kml_names[0], tmp)
            meta = _parse_kml(os.path.join(tmp, kml_names[0]))
    meta["file_type"] = "kmz"
    meta["source"] = os.path.basename(filepath)
    return meta


def _parse_kml(filepath: str) -> dict:
    try:
        tree = etree.parse(filepath)
    except etree.XMLSyntaxError:
        # Fall back to recovering parser for KMLs with undeclared namespace
        # prefixes (e.g. xsi:schemaLocation without xmlns:xsi) or other minor
        # malformations. lxml will skip the bad bits instead of bailing out.
        recovering = etree.XMLParser(recover=True)
        tree = etree.parse(filepath, parser=recovering)
    root = tree.getroot()
    if root is None:
        raise ValueError("could not parse KML (empty document after recovery)")

    # Strip namespace for easier xpath
    ns = KML_NS
    nsmap = {"k": "http://www.opengis.net/kml/2.2"}

    meta = {
        "file_type": "kml",
        "crs_epsg": 4326,  # KML is always WGS84
        "band_count": None,
        "resolution_x": None,
        "resolution_y": None,
        "width": None,
        "height": None,
        "nodata_value": None,
        "bit_depth": None,
        "compression": None,
        "data_type": None,
    }

    # ── Coordinates → bbox ────────────────────────────────────────────
    all_coords = []
    for coord_el in root.iter(f"{ns}coordinates"):
        text = coord_el.text
        if not text:
            continue
        for triplet in text.strip().split():
            parts = triplet.split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = float(parts[0]), float(parts[1])
                    all_coords.append((lon, lat))
                except ValueError:
                    continue

    if all_coords:
        lons = [c[0] for c in all_coords]
        lats = [c[1] for c in all_coords]
        meta["bbox_minx"] = min(lons)
        meta["bbox_miny"] = min(lats)
        meta["bbox_maxx"] = max(lons)
        meta["bbox_maxy"] = max(lats)
    else:
        meta["bbox_minx"] = meta["bbox_miny"] = None
        meta["bbox_maxx"] = meta["bbox_maxy"] = None

    # ── Features & geometry types ─────────────────────────────────────
    geom_tags = ["Point", "LineString", "Polygon",
                 "MultiGeometry", "LinearRing"]
    geom_counts = {}
    for tag in geom_tags:
        elems = root.iter(f"{ns}{tag}")
        count = sum(1 for _ in elems)
        if count > 0:
            geom_counts[tag] = count

    meta["feature_count"] = len(list(root.iter(f"{ns}Placemark")))
    meta["geometry_types"] = json.dumps(list(geom_counts.keys()))
    meta["geometry_type_counts"] = geom_counts

    # ── Layers (Folder names) ─────────────────────────────────────────
    layer_names = []
    for folder in root.iter(f"{ns}Folder"):
        name_el = folder.find(f"{ns}name")
        if name_el is not None and name_el.text:
            layer_names.append(name_el.text.strip())
    # Also include Document name
    for doc in root.iter(f"{ns}Document"):
        name_el = doc.find(f"{ns}name")
        if name_el is not None and name_el.text:
            layer_names.insert(0, name_el.text.strip())

    meta["layer_names"] = json.dumps(layer_names)

    # ── Temporal ──────────────────────────────────────────────────────
    timestamps = []
    for ts in root.iter(f"{ns}when"):
        if ts.text:
            timestamps.append(ts.text.strip())
    for ts_tag in ["begin", "end"]:
        for el in root.iter(f"{ns}{ts_tag}"):
            # TimeSpan/begin and end contain date text directly
            if el.text and el.text.strip():
                timestamps.append(el.text.strip())
            # TimeStamp uses a child <when>
            when = el.find(f"{ns}when")
            if when is not None and when.text:
                timestamps.append(when.text.strip())

    parsed_times = []
    for t in timestamps:
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                     "%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                parsed_times.append(datetime.strptime(t, fmt))
                break
            except ValueError:
                continue

    if parsed_times:
        meta["temporal_start"] = min(parsed_times).isoformat()
        meta["temporal_end"] = max(parsed_times).isoformat()
    else:
        meta["temporal_start"] = None
        meta["temporal_end"] = None

    # ── Description ───────────────────────────────────────────────────
    descriptions = []
    for desc in root.iter(f"{ns}description"):
        if desc.text:
            descriptions.append(desc.text.strip())
    meta["description"] = "; ".join(descriptions[:5]) if descriptions else None

    # ── Extended Data → custom_props ──────────────────────────────────
    custom = {}
    for ed in root.iter(f"{ns}ExtendedData"):
        for data in ed.iter(f"{ns}Data"):
            name = data.get("name")
            val_el = data.find(f"{ns}value")
            if name and val_el is not None and val_el.text:
                custom[name] = val_el.text.strip()
    meta["custom_props"] = json.dumps(custom) if custom else None

    # ── Tags (auto-generated) ─────────────────────────────────────────
    tags = ["kml"]
    if layer_names:
        tags.extend(layer_names[:5])
    for gt in geom_counts:
        tags.append(gt.lower())
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
