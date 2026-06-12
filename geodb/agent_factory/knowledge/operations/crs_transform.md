# CRS Transform Patterns

## Reproject coordinates
```python
from pyproj import Transformer

transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
x_utm, y_utm = transformer.transform(lon, lat)
```

## Reproject shapely geometry
```python
from shapely.ops import transform as shp_transform
from pyproj import Transformer

t = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
geom_utm = shp_transform(t.transform, geom_wgs84)
```

## Auto-detect UTM zone
```python
def get_utm_epsg(lon, lat):
    zone = int((lon + 180) / 6) + 1
    return 32600 + zone if lat >= 0 else 32700 + zone
```
