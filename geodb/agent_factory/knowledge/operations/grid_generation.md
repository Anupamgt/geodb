# Grid Generation Inside Polygon

## Generate regular grid points inside a polygon
```python
import numpy as np
from shapely.geometry import Point, Polygon
from pyproj import Transformer

# Project polygon to UTM for metric grid
transformer_to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
transformer_to_wgs = Transformer.from_crs(f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True)

# Transform polygon to UTM
from shapely.ops import transform as shp_transform
polygon_utm = shp_transform(transformer_to_utm.transform, polygon_wgs84)

# Generate grid
minx, miny, maxx, maxy = polygon_utm.bounds
xs = np.arange(minx, maxx, spacing_m)
ys = np.arange(miny, maxy, spacing_m)

points = []
for x in xs:
    for y in ys:
        pt = Point(x, y)
        if polygon_utm.contains(pt):
            lon, lat = transformer_to_wgs.transform(x, y)
            points.append((lon, lat))
```

## Determine UTM zone from longitude
```python
import math
def get_utm_epsg(lon, lat):
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return epsg
```
