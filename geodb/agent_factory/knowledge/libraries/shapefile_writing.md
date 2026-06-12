# Shapefile Writing Patterns

## Convert KML/KMZ to Shapefile using GeoPandas
```python
import zipfile, tempfile, os
import geopandas as gpd

# Step 1: Handle KMZ (unzip to get KML)
filepath = os.path.join(INPUT_DIR, 'input.kmz')
if filepath.lower().endswith('.kmz'):
    with zipfile.ZipFile(filepath, 'r') as z:
        kml_names = [n for n in z.namelist() if n.lower().endswith('.kml')]
        tmpdir = tempfile.mkdtemp()
        z.extract(kml_names[0], tmpdir)
        kml_path = os.path.join(tmpdir, kml_names[0])
else:
    kml_path = filepath

# Step 2: Read with GeoPandas
gdf = gpd.read_file(kml_path, driver="KML")

# Step 3: Ensure CRS is set (KML is always WGS84)
if gdf.crs is None:
    gdf = gdf.set_crs(epsg=4326)

# Step 4: Truncate column names to 10 chars (shapefile limit)
gdf.columns = [c[:10] if len(c) > 10 else c for c in gdf.columns]

# Step 5: Write shapefile
output_path = os.path.join(OUTPUT_DIR, 'output.shp')
gdf.to_file(output_path, driver="ESRI Shapefile")
```

## Convert GeoJSON to Shapefile
```python
import geopandas as gpd

gdf = gpd.read_file(os.path.join(INPUT_DIR, 'input.geojson'))
gdf.columns = [c[:10] if len(c) > 10 else c for c in gdf.columns]
gdf.to_file(os.path.join(OUTPUT_DIR, 'output.shp'), driver="ESRI Shapefile")
```

## Convert Shapefile to GeoJSON
```python
import geopandas as gpd

gdf = gpd.read_file(os.path.join(INPUT_DIR, 'input.shp'))
gdf.to_file(os.path.join(OUTPUT_DIR, 'output.geojson'), driver="GeoJSON")
```

## Write from lxml-parsed geometries to Shapefile
```python
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point
import pandas as pd

# After parsing KML with lxml (see kml_parsing patterns)
features = []
for geom, name in parsed_items:
    features.append({"geometry": geom, "name": name})

gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
gdf.to_file(os.path.join(OUTPUT_DIR, 'output.shp'), driver="ESRI Shapefile")
```

## Important notes
- Shapefile column names are limited to 10 characters — truncate before writing
- Shapefile writes multiple sidecar files (.shx, .dbf, .prj, .cpg) — all are needed
- Always set CRS before writing (KML data is always EPSG:4326)
- GeoPandas uses fiona under the hood for file I/O
