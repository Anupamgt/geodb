# KML/KMZ Parsing Patterns

## Parse KML with lxml
```python
import os
from lxml import etree
from shapely.geometry import Polygon, LineString, Point

kml_path = os.path.join(INPUT_DIR, 'doc.kml')  # use actual filename from step inputs
ns = "{http://www.opengis.net/kml/2.2}"
parser = etree.XMLParser(recover=True, huge_tree=True)
# IMPORTANT: open as file object, NOT path string (Windows spaces bug)
with open(kml_path, 'rb') as f:
    tree = etree.parse(f, parser)
root = tree.getroot()

features = []
for placemark in root.iter(f"{ns}Placemark"):
    name_el = placemark.find(f"{ns}name")
    feature_name = name_el.text.strip() if name_el is not None and name_el.text else ""

    coords_el = placemark.find(f".//{ns}coordinates")
    if coords_el is None or not coords_el.text:
        continue
    ring = []
    for triplet in coords_el.text.strip().split():
        parts = triplet.split(",")
        if len(parts) >= 2:
            lon, lat = float(parts[0]), float(parts[1])
            alt = float(parts[2]) if len(parts) >= 3 else 0.0
            ring.append((lon, lat, alt))

    # Detect geometry type
    if placemark.find(f".//{ns}Polygon") is not None:
        geom = Polygon([(c[0], c[1]) for c in ring])
    elif placemark.find(f".//{ns}LineString") is not None:
        geom = LineString([(c[0], c[1]) for c in ring])
    elif placemark.find(f".//{ns}Point") is not None and ring:
        geom = Point(ring[0][0], ring[0][1])
    else:
        continue

    features.append((geom, ring, {"name": feature_name}))
```

## Parse KMZ (unzip first)
KMZ files contain a file named `doc.kml` inside. Always output as `doc.kml`.
```python
import os
import zipfile

kmz_path = os.path.join(INPUT_DIR, 'input.kmz')  # use actual filename
with zipfile.ZipFile(kmz_path, 'r') as z:
    kml_names = [n for n in z.namelist() if n.lower().endswith('.kml')]
    z.extract(kml_names[0], OUTPUT_DIR)
    extracted = os.path.join(OUTPUT_DIR, kml_names[0])
    final_path = os.path.join(OUTPUT_DIR, 'doc.kml')
    if extracted != final_path:
        import shutil
        shutil.move(extracted, final_path)

print(f"Extracted KML to: {final_path}")
```

## Write GeoJSON from parsed geometries
```python
import os
import json

output_path = os.path.join(OUTPUT_DIR, 'output.geojson')  # use actual output filename
fc = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": geom.__geo_interface__,
            "properties": props,
        }
        for geom, ring, props in features
    ]
}
with open(output_path, "w") as f:
    json.dump(fc, f)

print(f"Wrote {len(fc['features'])} features to {output_path}")
```

## Write CSV from coordinates
```python
import os
import csv

output_path = os.path.join(OUTPUT_DIR, 'coordinates.csv')  # use actual output filename
with open(output_path, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['vertex_id', 'longitude', 'latitude', 'elevation'])
    vid = 1
    for geom, ring, props in features:
        for lon, lat, alt in ring:
            writer.writerow([vid, lon, lat, alt])
            vid += 1

print(f"Wrote {vid - 1} coordinates to {output_path}")
```
