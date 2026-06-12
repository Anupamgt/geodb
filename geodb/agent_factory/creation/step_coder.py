"""
Step Coder — generates Python code for a single sub-step.
Uses the agent's specialist system prompt for domain knowledge.
"""
import re


CODER_SYSTEM = """\
You are a geospatial Python developer. Write code for ONE specific step.

CRITICAL RULES — follow EXACTLY:
1. INPUT_DIR and OUTPUT_DIR are ALREADY defined as strings. Do NOT redefine them.
2. Read EVERY input file as: os.path.join(INPUT_DIR, 'exact_filename')
3. Write EVERY output file as: os.path.join(OUTPUT_DIR, 'exact_filename')
4. Use the EXACT filenames from "Input files" and "Output files" lists.
5. Code must be COMPLETE and RUNNABLE — not pseudocode.
6. For KML/XML parsing — ALWAYS use this safe pattern:
     from lxml import etree
     ns = '{http://www.opengis.net/kml/2.2}'
     with open(path, 'rb') as f:
         tree = etree.parse(f, etree.XMLParser(recover=True))
     root = tree.getroot()
     # Parse coordinates — split on whitespace, then on commas:
     for coord_el in root.iter(f'{ns}coordinates'):
         for token in (coord_el.text or '').split():
             parts = token.strip().split(',')
             if len(parts) >= 2:
                 lon, lat = float(parts[0]), float(parts[1])
     # ALWAYS guard rings before creating a Polygon:
     from shapely.geometry import Polygon
     rings = []  # list of coordinate lists
     for ring in rings:
         pts = [(c[0], c[1]) for c in ring]
         if len(pts) < 4:
             continue   # skip degenerate ring — do NOT raise
         geom = Polygon(pts)
7. Handle nodata/NaN values — skip or mark as None.
8. ALWAYS write the output file. The step is NOT complete without writing output.
9. Print a summary at the end: row count, file size, coordinate count, etc.
10. Output ONLY Python code inside ```python``` fences.
11. NEVER call a helper function you have not defined in this file. All logic must be
    self-contained. Never assume utilities like get_utm_epsg, shp_transform, etc. exist.
    For UTM EPSG from lon/lat, write inline:
        zone = int((lon + 180) / 6) + 1
        epsg = 32600 + zone if lat >= 0 else 32700 + zone
    For shapely transform, use:
        from shapely.ops import transform as shp_transform  (import it, do not invent it)

CRS / COORDINATE SYSTEM RULES — these are the most common source of silent bugs:

A. METRIC GRID CREATION (e.g. 20m x 20m mesh):
   - Input polygon is in WGS84 (lon/lat). You CANNOT use metres directly in WGS84.
   - Step 1 — detect UTM zone from polygon centroid and reproject polygon:
       from pyproj import Transformer
       from shapely.ops import transform as shp_transform
       lon_c = polygon_wgs84.centroid.x
       lat_c = polygon_wgs84.centroid.y
       zone = int((lon_c + 180) / 6) + 1
       utm_epsg = 32600 + zone if lat_c >= 0 else 32700 + zone
       to_utm = Transformer.from_crs('EPSG:4326', utm_epsg, always_xy=True)
       to_wgs = Transformer.from_crs(utm_epsg, 'EPSG:4326', always_xy=True)
       polygon_utm = shp_transform(to_utm.transform, polygon_wgs84)
   - Step 2 — build grid in UTM metres, then convert each point back to WGS84:
       import numpy as np
       from shapely.geometry import Point
       minx, miny, maxx, maxy = polygon_utm.bounds
       points_wgs84 = []
       for x in np.arange(minx, maxx, spacing_m):
           for y in np.arange(miny, maxy, spacing_m):
               if polygon_utm.contains(Point(x, y)):
                   lon, lat = to_wgs.transform(x, y)
                   points_wgs84.append((lon, lat))

B. RASTER SAMPLING (rasterio.sample / rasterio.index):
   - A raster can be in ANY CRS (UTM, local projected, geographic).
   - ALWAYS read the raster CRS first and reproject your coordinates to match it.
   - NEVER pass raw lon/lat to src.sample() unless you have confirmed src.crs == EPSG:4326.
   - Correct pattern:
       from pyproj import Transformer
       with rasterio.open(raster_path) as src:
           raster_crs = src.crs.to_epsg() or src.crs.to_wkt()
           t = Transformer.from_crs('EPSG:4326', src.crs, always_xy=True)
           coords_raster = [t.transform(lon, lat) for lon, lat in coords_wgs84]
           values = list(src.sample(coords_raster))
           nodata = src.nodata

C. REPROJECTING VECTOR DATA with geopandas:
   - Always call .to_crs() explicitly; never assume both datasets share a CRS.
       gdf = gdf.to_crs(epsg=target_epsg)

D. OUTPUT CRS:
   - Always output coordinates as WGS84 (lon, lat) in final files (GeoJSON, CSV, Excel)
     unless the user explicitly asked for a projected CRS.
   - Store heights/elevation as plain numeric values (metres or feet as in source data).

E. DISTANCE / AREA:
   - Always reproject to UTM before computing distances or areas.
   - Never use shapely .distance() or .area on WGS84 geometries for metric results.

TEMPLATE:
```python
import os
import json
# ... other imports ...

# Read inputs
input_path = os.path.join(INPUT_DIR, 'input_filename.ext')
# ... read and process ...

# Write output — THIS IS REQUIRED
output_path = os.path.join(OUTPUT_DIR, 'output_filename.ext')
with open(output_path, 'w') as f:
    # ... write results ...

print(f"Wrote {output_path}")
```
"""


def generate_step_code(step, agent_system_prompt: str, previous_steps: list,
                       parameters: dict, llm) -> str:
    """
    Generate code for a single step.

    Args:
        step: AgentStep to generate code for
        agent_system_prompt: the specialist prompt with domain knowledge/patterns
        previous_steps: list of completed steps (for context)
        parameters: agent parameters
        llm: LLMClient

    Returns: Python code string
    """
    # Build context from previous steps
    prev_context = ""
    if previous_steps:
        prev_context = "\nPREVIOUS STEPS (already completed, their outputs are in INPUT_DIR):\n"
        for ps in previous_steps:
            prev_context += f"  Step {ps.id} '{ps.name}': {ps.description}\n"
            prev_context += f"    Outputs: {ps.outputs}\n"
            if ps.output_summary:
                prev_context += f"    Result: {ps.output_summary}\n"

    prompt = f"""{agent_system_prompt}
{prev_context}
CURRENT STEP: Step {step.id} — {step.name}
  Description: {step.description}
  Input files (in INPUT_DIR): {step.inputs}
  Output files (write to OUTPUT_DIR): {step.outputs}
  Parameters: {parameters}

Write the Python code for THIS step only. INPUT_DIR and OUTPUT_DIR are already defined."""

    combined_system = CODER_SYSTEM
    raw = llm.generate(prompt, system=combined_system)
    return _extract_code(raw)


def fix_step_code(step, failed_code: str, error: str,
                  agent_system_prompt: str, llm) -> str:
    """Fix code that failed at runtime."""
    prompt = f"""{agent_system_prompt}

STEP: {step.name} — {step.description}
Input files: {step.inputs}
Output files: {step.outputs}

FAILED CODE:
```python
{failed_code}
```

ERROR:
```
{error[-1500:]}
```

Fix the code. Output complete corrected Python code.
If the error is NameError: 'X' is not defined — define the function inline or replace
the call with its logic directly. Never call a function you haven't defined.
For UTM EPSG inline: zone = int((lon+180)/6)+1; epsg = 32600+zone if lat>=0 else 32700+zone
For shapely transform: from shapely.ops import transform as shp_transform"""

    raw = llm.generate(prompt, system=CODER_SYSTEM)
    return _extract_code(raw)


def _extract_code(text):
    m = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    lines = text.strip().split("\n")
    code_lines = []
    started = False
    for line in lines:
        if line.strip().startswith(("import ", "from ", "#")):
            started = True
        if started:
            code_lines.append(line)
    return "\n".join(code_lines) if code_lines else text.strip()
