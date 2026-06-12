"""
Agent 1 — Planner
Truly general-purpose: maps user's EXACT task to a step plan.
Never defaults to grid/xlsx unless explicitly asked.
"""
import json
import re
import os
import zipfile
from geodb.transform.config import GEO_LIBRARIES_CONTEXT
from geodb.transform.pipeline.step import Step, StepPlan


SYSTEM = """\
You are a geospatial pipeline planner. Given a user's task and uploaded files,
produce an EXACT step-by-step plan that does PRECISELY what the user asked.

CRITICAL RULES:
1. Do EXACTLY what the user asked. Do NOT add extra operations they did not request.
2. If the user says "plot" / "show" / "visualize" / "map" → output is an HTML map file,
   NOT an Excel spreadsheet.
3. If the user says "image" / "picture" / "png" / "save as image" → use matplotlib to save PNG.
4. Only output xlsx/csv if user explicitly asks for tabular data / spreadsheet / Excel.
5. Use the ACTUAL uploaded filenames in step inputs. Never invent filenames like "area.kml".
6. KMZ files are zipped KML — first step must unzip to extract the .kml inside.

OUTPUT FORMAT DETECTION (follow strictly):
  "plot", "map", "show on map", "display", "visualize" → format = "html"
  "image", "picture", "png", "jpg", "save as image"    → format = "png"
  "excel", "spreadsheet", "xlsx"                        → format = "xlsx"
  "csv", "table", "tabular"                             → format = "csv"
  "shapefile", "shp"                                    → format = "shp"
  "geojson"                                             → format = "geojson"
  "kml"                                                 → format = "kml"
  "tif", "raster", "geotiff"                            → format = "tif"
  No format specified → choose the most natural for the task

EXAMPLE TASKS AND THEIR CORRECT PLANS:

Task: "plot the points on a map"
→ Steps: 1) parse input file → GeoJSON  2) generate HTML map with Leaflet
→ Output format: html (NOT xlsx)

Task: "extract heights at 20m grid"
→ Steps: 1) parse polygon  2) generate grid  3) sample DEM  4) export CSV/Excel
→ Output format: xlsx or csv

Task: "show DEM as heatmap"
→ Steps: 1) read raster  2) generate HTML with color-mapped raster overlay
→ Output format: html

Task: "clip DEM to polygon boundary"
→ Steps: 1) parse polygon  2) clip raster with mask  3) save clipped TIF
→ Output format: tif

Task: "calculate area of all polygons"
→ Steps: 1) parse polygons  2) compute area/perimeter in UTM  3) export results
→ Output format: csv or xlsx

Task: "convert KML to shapefile"
→ Steps: 1) parse KML  2) write as shapefile
→ Output format: shp

Task: "create elevation profile along a line"
→ Steps: 1) parse line  2) sample DEM along line  3) generate profile chart HTML
→ Output format: html

Output ONLY valid JSON inside ```json``` fences. No commentary.

JSON format:
{
  "task": "exactly what user asked",
  "input_files": [{"name": "ACTUAL_FILENAME.ext", "type": "ext", "role": "what it provides"}],
  "output": {"format": "html|png|xlsx|csv|tif|shp|geojson|kml", "description": "what output contains"},
  "parameters": {},
  "steps": [
    {
      "id": 1,
      "name": "snake_case_name",
      "description": "What this step does, which libraries to use, how to handle edge cases",
      "inputs": ["ACTUAL_FILENAME.ext"],
      "outputs": ["intermediate_or_final_output.ext"],
      "needs": [],
      "viz_hint": "map_polygon|map_points|map_colored_points|map_lines|histogram|line_chart|heatmap|raster_preview|table_preview|comparison_map|profile_chart|contour_map|scatter_plot"
    }
  ]
}

STEP RULES:
- Use the ACTUAL uploaded filenames in inputs. Never use generic names.
- KMZ → first step unzips, extracts .kml, then parses
- For HTML map output: final step generates self-contained HTML with Leaflet.js + embedded data
- For PNG output: final step uses matplotlib to render and save
- For TIF output: use rasterio to write GeoTIFF
- For SHP output: use geopandas to_file with driver='ESRI Shapefile'
- Intermediate formats: GeoJSON for vectors, CSV for tabular, TIF for rasters
- 2-5 steps. Simpler is better.
- Always mention CRS handling and nodata handling in descriptions
"""


def run(task: str, files: list, llm, examples: list = None) -> StepPlan:
    """Generate a step plan from the task description."""
    prompt = _build_prompt(task, files, examples)
    raw = llm.generate(prompt, system=SYSTEM)
    plan_dict = _extract_json(raw)
    # Post-process: ensure actual filenames are used
    plan_dict = _fix_filenames(plan_dict, files)
    return _parse_plan(plan_dict)


def _build_prompt(task: str, files: list, examples: list = None) -> str:
    parts = [GEO_LIBRARIES_CONTEXT, "\nUPLOADED FILES (use these EXACT filenames in your plan):"]
    for f in files:
        meta = f.get("metadata", {})
        desc = f"  - {f['name']} ({f['type']}"
        if meta.get("feature_count"):
            desc += f", {meta['feature_count']} features"
        if meta.get("geometry_types"):
            desc += f", geometry: {meta['geometry_types']}"
        if meta.get("bands"):
            desc += f", {meta['bands']} band(s), {meta.get('dtype','')}"
        if meta.get("resolution"):
            desc += f", resolution: {meta['resolution']}"
        if meta.get("bounds"):
            desc += f", bounds: {meta['bounds']}"
        if meta.get("width") and meta.get("height"):
            desc += f", {meta['width']}x{meta['height']} px"
        desc += f", size: {f.get('size',0)/1024:.1f} KB)"
        parts.append(desc)

    # Only include examples if they're highly relevant (score threshold)
    if examples:
        parts.append("\nREFERENCE EXAMPLES (adapt to user's actual request, do NOT copy blindly):")
        for ex in examples[:1]:  # Only 1 example max to reduce bias
            parts.append(f"  Example task: {ex.get('task', '')}")
            parts.append(f"  Example output format: {ex.get('output', {}).get('format', '?')}")

    parts.append(f"\nUSER TASK: {task}")
    parts.append("\nGenerate the step plan JSON. Match the output format to what the user wants.")
    return "\n".join(parts)


def _fix_filenames(plan_dict: dict, files: list) -> dict:
    """
    Post-process: replace generic/wrong filenames with actual uploaded filenames.
    E.g. if plan says "area.kml" but user uploaded "DEM_demo.kmz", fix it.
    """
    actual_names = {f["type"]: f["name"] for f in files}
    # Also map by extension variations
    actual_names_by_ext = {}
    for f in files:
        ext = f["type"]
        actual_names_by_ext[ext] = f["name"]
        if ext == "kmz":
            actual_names_by_ext["kml"] = f["name"]  # KMZ contains KML

    for step in plan_dict.get("steps", []):
        fixed_inputs = []
        for inp in step.get("inputs", []):
            ext = os.path.splitext(inp)[1].lstrip(".").lower()
            # If this filename doesn't match any actual file, replace it
            actual = [f["name"] for f in files]
            if inp not in actual:
                replacement = actual_names_by_ext.get(ext, inp)
                fixed_inputs.append(replacement)
            else:
                fixed_inputs.append(inp)
        step["inputs"] = fixed_inputs

    # Fix input_files section too
    plan_dict["input_files"] = [
        {"name": f["name"], "type": f["type"], "role": f.get("metadata", {}).get("role", f["type"] + " file")}
        for f in files
    ]

    return plan_dict


def _extract_json(text: str) -> dict:
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"Could not extract JSON from LLM response:\n{text[:500]}")


def _parse_plan(d: dict) -> StepPlan:
    plan = StepPlan(
        task=d.get("task", ""),
        input_files=d.get("input_files", []),
        output=d.get("output", {}),
        parameters=d.get("parameters", {}),
    )
    for s in d.get("steps", []):
        plan.steps.append(Step(
            id=s["id"],
            name=s.get("name", f"step_{s['id']}"),
            description=s.get("description", ""),
            inputs=s.get("inputs", []),
            outputs=s.get("outputs", []),
            needs=s.get("needs", []),
            viz_hint=s.get("viz_hint", ""),
        ))
    return plan


def inspect_file(filepath: str) -> dict:
    """Quick inspection of an uploaded file for the planner prompt."""
    ext = os.path.splitext(filepath)[1].lower().lstrip(".")
    info = {
        "name": os.path.basename(filepath),
        "type": ext,
        "size": os.path.getsize(filepath),
        "metadata": {},
    }

    try:
        if ext == "kml":
            info["metadata"] = _inspect_kml(filepath)
        elif ext == "kmz":
            info["metadata"] = _inspect_kmz(filepath)
        elif ext in ("tif", "tiff"):
            info["metadata"] = _inspect_tif(filepath)
        elif ext == "geojson":
            info["metadata"] = _inspect_geojson(filepath)
        elif ext == "csv":
            info["metadata"] = _inspect_csv(filepath)
        elif ext in ("shp",):
            info["metadata"] = {"type": "shapefile"}
    except Exception as e:
        info["metadata"]["error"] = str(e)

    return info


def _inspect_kmz(path: str) -> dict:
    """KMZ is a zipped KML."""
    meta = {"is_kmz": True}
    try:
        with zipfile.ZipFile(path, 'r') as z:
            kml_files = [n for n in z.namelist() if n.lower().endswith('.kml')]
            meta["contained_files"] = z.namelist()
            meta["kml_files"] = kml_files
            if kml_files:
                # Extract and inspect the first KML
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    z.extract(kml_files[0], tmpdir)
                    kml_meta = _inspect_kml(os.path.join(tmpdir, kml_files[0]))
                    meta.update(kml_meta)
    except Exception as e:
        meta["error"] = str(e)
    return meta


def _inspect_kml(path: str) -> dict:
    from lxml import etree
    ns = "{http://www.opengis.net/kml/2.2}"
    parser = etree.XMLParser(recover=True)
    tree = etree.parse(path, parser)
    root = tree.getroot()
    features = len(list(root.iter(f"{ns}Placemark")))

    geom_types = []
    for tag in ("Point", "LineString", "Polygon", "MultiGeometry"):
        if list(root.iter(f"{ns}{tag}")):
            geom_types.append(tag)

    coords = []
    for el in root.iter(f"{ns}coordinates"):
        if el.text:
            for t in el.text.strip().split():
                parts = t.split(",")
                if len(parts) >= 2:
                    try:
                        coords.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        pass

    bounds = None
    if coords:
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        bounds = [round(min(lons), 6), round(min(lats), 6),
                  round(max(lons), 6), round(max(lats), 6)]

    return {
        "feature_count": features,
        "geometry_types": geom_types,
        "bounds": bounds,
    }


def _inspect_tif(path: str) -> dict:
    import rasterio
    with rasterio.open(path) as ds:
        return {
            "bands": ds.count,
            "width": ds.width,
            "height": ds.height,
            "crs": str(ds.crs),
            "bounds": [round(b, 6) for b in ds.bounds],
            "resolution": [round(r, 6) for r in ds.res],
            "dtype": str(ds.dtypes[0]),
            "nodata": ds.nodata,
        }


def _inspect_geojson(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    features = data.get("features", [])
    gtypes = set(f.get("geometry", {}).get("type", "") for f in features)
    return {"feature_count": len(features), "geometry_types": list(gtypes)}


def _inspect_csv(path: str) -> dict:
    import csv as csv_mod
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv_mod.reader(f)
        headers = next(reader, [])
        row_count = sum(1 for _ in reader)
    return {"columns": headers, "rows": row_count}
