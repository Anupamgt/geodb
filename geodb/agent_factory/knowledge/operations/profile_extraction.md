# Profile/Cross-Section Extraction

## Find major axis of polygon (longest dimension)
```python
from shapely.geometry import LineString
from shapely import minimum_rotated_rectangle

mrr = minimum_rotated_rectangle(polygon)
coords = list(mrr.exterior.coords)
edges = []
for i in range(len(coords)-1):
    edge = LineString([coords[i], coords[i+1]])
    edges.append((edge.length, edge))
edges.sort(key=lambda x: -x[0])
major_axis = edges[0][1]  # longest edge = major axis direction
```

## Generate points along a line at regular intervals
```python
from shapely.geometry import Point

total_length = line_utm.length
distances = np.arange(0, total_length, interval_m)
points = []
for d in distances:
    pt = line_utm.interpolate(d)
    points.append((d, pt.x, pt.y))
```

## Full profile workflow
```python
# 1. Get polygon major axis as a line
# 2. Project to UTM for metric spacing
# 3. Generate points along line at interval
# 4. Project points back to WGS84
# 5. Sample DEM at each point
# 6. Output: point_id, distance_m, lat, lon, height_m
```
