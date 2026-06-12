"""
Example library — builtin and user-added example pipelines.
The planner agent uses matching examples as few-shot references.
"""
import json
import os
from geodb.transform.config import EXAMPLES_DIR, PIPELINES_DIR


def find_matching(task: str, input_types: list, max_results: int = 2) -> list:
    """
    Find examples that best match the given task and input file types.

    Args:
        task: user's task description
        input_types: list of file extensions e.g. ['kml', 'tif']
        max_results: max examples to return

    Returns: list of example dicts (each has 'task', 'steps', etc.)
    """
    all_examples = _load_all()
    scored = []

    task_lower = task.lower()
    task_words = set(task_lower.split())

    # Semantic keyword groups — if user's task contains these, boost examples
    # whose output format or operation matches
    OUTPUT_HINTS = {
        "html": ["plot", "map", "show", "display", "visualize", "visualise", "view", "render", "interactive"],
        "shp": ["shapefile", "shp", "esri", "arcgis"],
        "csv": ["table", "csv", "coordinates", "extract", "list", "tabular"],
        "xlsx": ["excel", "xlsx", "spreadsheet"],
        "tif": ["raster", "tif", "geotiff", "clip", "crop", "slope", "aspect"],
        "png": ["image", "picture", "png", "jpg", "plot", "chart", "figure"],
        "kml": ["kml", "google earth"],
    }

    # Operation keywords
    OP_KEYWORDS = {
        "clip": ["clip", "crop", "mask", "cut", "trim"],
        "convert": ["convert", "transform", "export", "shapefile", "shp"],
        "plot": ["plot", "map", "show", "display", "visualize", "render", "view"],
        "extract": ["extract", "sample", "height", "elevation", "grid", "profile"],
        "slope": ["slope", "aspect", "gradient", "terrain"],
        "area": ["area", "perimeter", "measure", "calculate"],
        "contour": ["contour", "isolines"],
        "coordinates": ["coordinates", "vertices", "points", "lat", "lon"],
    }

    for ex in all_examples:
        score = 0
        ex_task_lower = ex.get("task", "").lower()
        ex_words = set(ex_task_lower.split())
        ex_fmt = ex.get("output", {}).get("format", "")

        # 1. File type overlap (less weight to prevent type-only matching)
        ex_types = set(i.get("type", "") for i in ex.get("required_inputs", []))
        type_overlap = len(set(input_types) & ex_types)
        score += type_overlap * 5

        # 2. Direct word overlap
        word_overlap = len(task_words & ex_words)
        score += word_overlap * 3

        # 3. Output format hint matching (high weight)
        for fmt, hints in OUTPUT_HINTS.items():
            user_wants_fmt = any(h in task_lower for h in hints)
            if user_wants_fmt and ex_fmt == fmt:
                score += 20

        # 4. Operation keyword matching (high weight)
        for op, keywords in OP_KEYWORDS.items():
            user_wants_op = any(k in task_lower for k in keywords)
            ex_has_op = any(k in ex_task_lower for k in keywords)
            if user_wants_op and ex_has_op:
                score += 15

        # 5. PENALTY: if user clearly wants a different output format, skip
        user_fmt = None
        for fmt, hints in OUTPUT_HINTS.items():
            if any(h in task_lower for h in hints):
                user_fmt = fmt
                break
        if user_fmt and ex_fmt and user_fmt != ex_fmt:
            score -= 25  # Heavy penalty for format mismatch

        if score >= 15:  # Minimum threshold to be considered relevant
            scored.append((score, ex))

    scored.sort(key=lambda x: -x[0])
    return [ex for _, ex in scored[:max_results]]


def add_from_template(template_id: str, name: str, description: str):
    """Promote a saved template to an example."""
    from geodb.transform.storage.template import load
    doc = load(template_id)
    doc["example_name"] = name
    doc["example_description"] = description

    os.makedirs(EXAMPLES_DIR, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "_ " else "" for c in name)
    safe_name = "_".join(safe_name.lower().split())
    path = os.path.join(EXAMPLES_DIR, f"{safe_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, default=str)


def list_examples() -> list:
    """List all available examples."""
    result = []
    for ex in _load_all():
        result.append({
            "name": ex.get("example_name", ex.get("template_id", "?")),
            "task": ex.get("task", ""),
            "inputs": [i.get("type") for i in ex.get("required_inputs", [])],
            "steps": len(ex.get("steps", [])),
        })
    return result


def _load_all() -> list:
    """Load all examples from builtin and user dirs."""
    examples = []
    for directory in [EXAMPLES_DIR, PIPELINES_DIR]:
        if not os.path.isdir(directory):
            continue
        for f in os.listdir(directory):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(directory, f)) as fh:
                        examples.append(json.load(fh))
                except Exception:
                    pass
    return examples


# ── Builtin examples (created on first import if missing) ────────────────────

BUILTIN_EXAMPLES = [
    {
        "template_id": "dem_height_at_grid",
        "task": "Extract elevation heights at regular grid points inside a polygon from a DEM",
        "required_inputs": [
            {"type": "kml", "role": "polygon boundary"},
            {"type": "tif", "role": "DEM elevation raster"},
        ],
        "output": {"format": "xlsx", "description": "Excel with point_id, lat, lon, height_m"},
        "parameters": {"grid_spacing_m": 20},
        "steps": [
            {"id": 1, "name": "parse_polygon", "description": "Read KML, extract polygon as GeoJSON",
             "inputs": ["area.kml"], "outputs": ["polygon.geojson"], "needs": [], "viz_hint": "map_polygon"},
            {"id": 2, "name": "generate_grid", "description": "Create regular grid points inside polygon, project to UTM for metric spacing",
             "inputs": ["polygon.geojson"], "outputs": ["grid_points.csv"], "needs": [1], "viz_hint": "map_points"},
            {"id": 3, "name": "sample_dem", "description": "Sample DEM raster at each grid point to get elevation, handle nodata",
             "inputs": ["grid_points.csv", "dem.tif"], "outputs": ["heights.csv"], "needs": [2], "viz_hint": "map_colored_points"},
            {"id": 4, "name": "export_excel", "description": "Write results to formatted Excel",
             "inputs": ["heights.csv"], "outputs": ["output.xlsx"], "needs": [3], "viz_hint": "table_preview"},
        ],
    },
    {
        "template_id": "dem_cross_section",
        "task": "Extract elevation profile / cross section along a line from a DEM",
        "required_inputs": [
            {"type": "kml", "role": "line / path geometry"},
            {"type": "tif", "role": "DEM elevation raster"},
        ],
        "output": {"format": "csv", "description": "CSV with distance_m, lat, lon, elevation_m"},
        "parameters": {"sample_interval_m": 10},
        "steps": [
            {"id": 1, "name": "parse_line", "description": "Read KML, extract line geometry as GeoJSON",
             "inputs": ["line.kml"], "outputs": ["line.geojson"], "needs": [], "viz_hint": "map_lines"},
            {"id": 2, "name": "sample_along_line", "description": "Generate points at regular intervals along the line, sample DEM at each",
             "inputs": ["line.geojson", "dem.tif"], "outputs": ["profile.csv"], "needs": [1], "viz_hint": "line_chart"},
            {"id": 3, "name": "export", "description": "Final profile CSV",
             "inputs": ["profile.csv"], "outputs": ["cross_section.csv"], "needs": [2], "viz_hint": "table_preview"},
        ],
    },
    {
        "template_id": "polygon_area_report",
        "task": "Calculate area and perimeter of polygons in a KML file",
        "required_inputs": [
            {"type": "kml", "role": "polygons"},
        ],
        "output": {"format": "xlsx", "description": "Excel with polygon_id, area_ha, perimeter_m, centroid_lat, centroid_lon"},
        "parameters": {},
        "steps": [
            {"id": 1, "name": "parse_polygons", "description": "Read KML, extract all polygons as GeoDataFrame",
             "inputs": ["area.kml"], "outputs": ["polygons.geojson"], "needs": [], "viz_hint": "map_polygon"},
            {"id": 2, "name": "compute_metrics", "description": "Project to UTM, calculate area(ha), perimeter(m), centroid for each polygon",
             "inputs": ["polygons.geojson"], "outputs": ["metrics.csv"], "needs": [1], "viz_hint": "table_preview"},
            {"id": 3, "name": "export_excel", "description": "Write formatted Excel report",
             "inputs": ["metrics.csv"], "outputs": ["area_report.xlsx"], "needs": [2], "viz_hint": "table_preview"},
        ],
    },
    {
        "template_id": "plot_on_map",
        "task": "Plot geometries from KML/KMZ on an interactive map",
        "required_inputs": [
            {"type": "kml", "role": "geometries to plot"},
        ],
        "output": {"format": "html", "description": "Interactive HTML map with Leaflet showing all geometries"},
        "parameters": {},
        "steps": [
            {"id": 1, "name": "parse_geometry", "description": "Read KML/KMZ, extract all geometries as GeoJSON. For KMZ, unzip first to get the KML inside.",
             "inputs": ["input.kml"], "outputs": ["features.geojson"], "needs": [], "viz_hint": "map_polygon"},
            {"id": 2, "name": "generate_map", "description": "Create a self-contained HTML file with Leaflet.js that displays all geometries on an OpenStreetMap basemap. Color polygons, lines, points differently. Auto-fit map bounds. Add popups with properties.",
             "inputs": ["features.geojson"], "outputs": ["map.html"], "needs": [1], "viz_hint": "map_polygon"},
        ],
    },
    {
        "template_id": "clip_raster_to_polygon",
        "task": "Clip/crop a raster (DEM/TIF) to a polygon boundary from KML",
        "required_inputs": [
            {"type": "kml", "role": "clip boundary polygon"},
            {"type": "tif", "role": "raster to clip"},
        ],
        "output": {"format": "tif", "description": "Clipped GeoTIFF containing only the area inside the polygon"},
        "parameters": {},
        "steps": [
            {"id": 1, "name": "parse_polygon", "description": "Read KML, extract polygon geometry as GeoJSON",
             "inputs": ["boundary.kml"], "outputs": ["polygon.geojson"], "needs": [], "viz_hint": "map_polygon"},
            {"id": 2, "name": "clip_raster", "description": "Use rasterio.mask to clip the raster to the polygon. Handle CRS mismatch by reprojecting polygon if needed.",
             "inputs": ["polygon.geojson", "input.tif"], "outputs": ["clipped.tif"], "needs": [1], "viz_hint": "raster_preview"},
        ],
    },
    {
        "template_id": "kml_to_shapefile",
        "task": "Convert KML file to Shapefile format",
        "required_inputs": [
            {"type": "kml", "role": "input geometry"},
        ],
        "output": {"format": "shp", "description": "ESRI Shapefile (.shp + sidecar files)"},
        "parameters": {},
        "steps": [
            {"id": 1, "name": "parse_kml", "description": "Read KML/KMZ, extract features as GeoDataFrame",
             "inputs": ["input.kml"], "outputs": ["features.geojson"], "needs": [], "viz_hint": "map_polygon"},
            {"id": 2, "name": "export_shapefile", "description": "Write GeoDataFrame to Shapefile format using geopandas",
             "inputs": ["features.geojson"], "outputs": ["output.shp"], "needs": [1], "viz_hint": "map_polygon"},
        ],
    },
    {
        "template_id": "dem_slope_map",
        "task": "Generate slope map from DEM raster",
        "required_inputs": [
            {"type": "tif", "role": "DEM elevation raster"},
        ],
        "output": {"format": "tif", "description": "Slope raster in degrees"},
        "parameters": {},
        "steps": [
            {"id": 1, "name": "compute_slope", "description": "Read DEM, compute slope using numpy gradient, save as GeoTIFF with same CRS/transform",
             "inputs": ["dem.tif"], "outputs": ["slope.tif"], "needs": [], "viz_hint": "raster_preview"},
            {"id": 2, "name": "generate_report", "description": "Create summary CSV with slope statistics (min, max, mean, std) and classification counts",
             "inputs": ["slope.tif"], "outputs": ["slope_stats.csv"], "needs": [1], "viz_hint": "histogram"},
        ],
    },
    {
        "template_id": "visualize_dem_3d",
        "task": "Create a visualization of DEM elevation data",
        "required_inputs": [
            {"type": "tif", "role": "DEM elevation raster"},
        ],
        "output": {"format": "html", "description": "Interactive HTML with elevation heatmap and histogram"},
        "parameters": {},
        "steps": [
            {"id": 1, "name": "extract_data", "description": "Read DEM, downsample for visualization, extract elevation grid and bounds",
             "inputs": ["dem.tif"], "outputs": ["elevation_data.csv"], "needs": [], "viz_hint": "heatmap"},
            {"id": 2, "name": "generate_viz", "description": "Create self-contained HTML with Leaflet heatmap of elevation + Plotly histogram of elevation distribution",
             "inputs": ["elevation_data.csv"], "outputs": ["dem_viz.html"], "needs": [1], "viz_hint": "heatmap"},
        ],
    },
    {
        "template_id": "extract_coordinates",
        "task": "Extract all coordinates/vertices from a KML as a table",
        "required_inputs": [
            {"type": "kml", "role": "input geometry"},
        ],
        "output": {"format": "csv", "description": "CSV with point_id, latitude, longitude, feature_name"},
        "parameters": {},
        "steps": [
            {"id": 1, "name": "parse_and_extract", "description": "Read KML, iterate all placemarks, extract every coordinate vertex with its feature name",
             "inputs": ["input.kml"], "outputs": ["coordinates.csv"], "needs": [], "viz_hint": "map_points"},
        ],
    },
]


def ensure_builtins():
    """Write builtin examples to disk (overwrite to pick up new ones)."""
    os.makedirs(EXAMPLES_DIR, exist_ok=True)
    for ex in BUILTIN_EXAMPLES:
        path = os.path.join(EXAMPLES_DIR, f"{ex['template_id']}.json")
        with open(path, "w") as f:
            json.dump(ex, f, indent=2)
