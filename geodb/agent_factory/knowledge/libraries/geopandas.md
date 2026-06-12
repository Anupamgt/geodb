# GeoPandas Patterns

## Read vector files (KML, GeoJSON, Shapefile)
```python
import geopandas as gpd

gdf = gpd.read_file(filepath)
# For KML inside KMZ, extract KML first then read
gdf = gpd.read_file(kml_path, driver="KML")
```

## Read KMZ via unzip + GeoPandas
```python
import zipfile, tempfile, os
import geopandas as gpd

if filepath.lower().endswith('.kmz'):
    with zipfile.ZipFile(filepath, 'r') as z:
        kml_names = [n for n in z.namelist() if n.lower().endswith('.kml')]
        tmpdir = tempfile.mkdtemp()
        z.extract(kml_names[0], tmpdir)
        kml_path = os.path.join(tmpdir, kml_names[0])
else:
    kml_path = filepath

gdf = gpd.read_file(kml_path, driver="KML")
```

## Write to Shapefile
```python
import geopandas as gpd

# Shapefile column names are limited to 10 characters
gdf.to_file(output_path, driver="ESRI Shapefile")
```

## Write to GeoJSON
```python
gdf.to_file(output_path, driver="GeoJSON")
```

## Write to KML
```python
import fiona
fiona.supported_drivers['KML'] = 'rw'
gdf.to_file(output_path, driver="KML")
```

## CRS handling
```python
# Check CRS
print(gdf.crs)

# Reproject
gdf_utm = gdf.to_crs(epsg=32643)  # UTM zone 43N (for India)
gdf_wgs84 = gdf.to_crs(epsg=4326)  # back to WGS84

# Set CRS if missing
gdf = gdf.set_crs(epsg=4326)
```

## Geometry operations
```python
# Area (in CRS units — reproject to metric CRS first)
gdf_utm = gdf.to_crs(epsg=32643)
gdf['area_m2'] = gdf_utm.geometry.area

# Length
gdf['length_m'] = gdf_utm.geometry.length

# Centroid
gdf['centroid'] = gdf.geometry.centroid

# Bounds
gdf['bounds'] = gdf.geometry.bounds
```
