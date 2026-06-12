# Geometry Measurement Patterns

## Area and perimeter in metric units
```python
from pyproj import Transformer
from shapely.ops import transform as shp_transform

# Project to UTM
utm_epsg = get_utm_epsg(centroid_lon, centroid_lat)
t = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
geom_utm = shp_transform(t.transform, geom_wgs84)

area_sqm = geom_utm.area
area_ha = area_sqm / 10000
perimeter_m = geom_utm.length
centroid = geom_wgs84.centroid
```
