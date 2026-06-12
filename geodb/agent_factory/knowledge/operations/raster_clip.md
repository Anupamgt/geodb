# Raster Clipping Patterns

## Clip raster with polygon mask
```python
import rasterio
from rasterio.mask import mask
from shapely.geometry import mapping
import json

with open(polygon_geojson) as f:
    geojson = json.load(f)
shapes = [feature["geometry"] for feature in geojson["features"]]

with rasterio.open(input_tif) as src:
    out_image, out_transform = mask(src, shapes, crop=True)
    out_meta = src.meta.copy()
    out_meta.update({
        "height": out_image.shape[1],
        "width": out_image.shape[2],
        "transform": out_transform,
    })

with rasterio.open(output_tif, "w", **out_meta) as dst:
    dst.write(out_image)
```
