# Rasterio Patterns

## Read raster
```python
import rasterio
with rasterio.open(path) as src:
    data = src.read(1)  # first band
    bounds = src.bounds
    transform = src.transform
    crs = src.crs
    nodata = src.nodata
```

## Write raster
```python
import rasterio
from rasterio.crs import CRS
meta = {"driver": "GTiff", "height": h, "width": w, "count": 1,
        "dtype": "float32", "crs": CRS.from_epsg(4326), "transform": transform}
with rasterio.open(path, "w", **meta) as dst:
    dst.write(data, 1)
```
