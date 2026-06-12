# DEM Sampling Patterns

## Sample raster at specific points
```python
import os
import rasterio
import numpy as np

dem_path = os.path.join(INPUT_DIR, 'DEM_demo.tif')  # use actual filename from step inputs
with rasterio.open(dem_path) as src:
    # coords must be list of (lon, lat) tuples
    coords = [(lon, lat) for lon, lat in zip(lons, lats)]
    values = list(src.sample(coords))
    heights = []
    for v in values:
        val = float(v[0])
        if src.nodata is not None and abs(val - src.nodata) < 0.01:
            heights.append(None)
        else:
            heights.append(val)
```

## Check if point is within raster bounds
```python
with rasterio.open(dem_path) as src:
    b = src.bounds
    valid = b.left <= lon <= b.right and b.bottom <= lat <= b.top
```

## Full workflow: read GeoJSON coords, sample DEM, write CSV
```python
import os
import json
import csv
import rasterio

# Read coordinates from GeoJSON
geojson_path = os.path.join(INPUT_DIR, 'geometry.geojson')  # use actual input filename
with open(geojson_path, 'r') as f:
    data = json.load(f)

# Extract all coordinates
coords = []
for feature in data['features']:
    geom = feature['geometry']
    if geom['type'] == 'Polygon':
        for ring in geom['coordinates']:
            for c in ring:
                coords.append((c[0], c[1]))  # lon, lat
    elif geom['type'] == 'LineString':
        for c in geom['coordinates']:
            coords.append((c[0], c[1]))
    elif geom['type'] == 'Point':
        c = geom['coordinates']
        coords.append((c[0], c[1]))

# Sample DEM
dem_path = os.path.join(INPUT_DIR, 'DEM_demo.tif')  # use actual DEM filename
with rasterio.open(dem_path) as src:
    sampled = list(src.sample(coords))
    nodata = src.nodata

# Write CSV output
output_path = os.path.join(OUTPUT_DIR, 'output.csv')  # use actual output filename
with open(output_path, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['vertex_id', 'longitude', 'latitude', 'elevation_m'])
    for i, ((lon, lat), val) in enumerate(zip(coords, sampled), 1):
        elev = float(val[0])
        if nodata is not None and abs(elev - nodata) < 0.01:
            elev = None
        writer.writerow([i, lon, lat, elev])

print(f"Wrote {len(coords)} sampled points to {output_path}")
```
