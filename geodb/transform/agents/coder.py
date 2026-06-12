"""
Agent 2 — Coder
Takes: step description + input file info + previous step context
Produces: executable Python code string
"""
import re
from geodb.transform.config import GEO_LIBRARIES_CONTEXT


SYSTEM = """\
You are a geospatial Python developer. You write code to perform one specific
transformation step on geospatial data. You can produce ANY output format.

Output ONLY Python code inside ```python``` fences. No commentary before or after.

RULES:
- Input files are in the directory stored in variable INPUT_DIR (already defined)
- Write output files to the directory stored in variable OUTPUT_DIR (already defined)
- Use: input_path = os.path.join(INPUT_DIR, 'filename.ext')
- Use: output_path = os.path.join(OUTPUT_DIR, 'filename.ext')
- Always import what you need at the top
- Handle nodata / NaN values
- Print a summary at the end (e.g. "Produced 847 grid points")
- Keep code clean, straightforward, well-commented
- Do NOT use subprocess, os.system, requests, or any network calls
- Do NOT use eval() or exec()
- CRITICAL: Do NOT call any function you have not defined in this file.
  Every helper function must be defined in the same code block before it is called.
  Never assume utilities like get_utm_epsg, calc_zone, etc. exist — write the logic inline.
  For UTM EPSG from lon/lat, use inline:
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone

CRS / COORDINATE SYSTEM RULES — these are the most common source of silent bugs:

A. METRIC GRID CREATION (e.g. 20m x 20m mesh):
   - Input polygon is in WGS84 (lon/lat). You CANNOT use metres directly in WGS84.
   - Detect UTM zone and reproject BEFORE building the grid:
       from pyproj import Transformer
       from shapely.ops import transform as shp_transform
       lon_c = polygon_wgs84.centroid.x; lat_c = polygon_wgs84.centroid.y
       zone = int((lon_c + 180) / 6) + 1
       utm_epsg = 32600 + zone if lat_c >= 0 else 32700 + zone
       to_utm = Transformer.from_crs('EPSG:4326', utm_epsg, always_xy=True)
       to_wgs = Transformer.from_crs(utm_epsg, 'EPSG:4326', always_xy=True)
       polygon_utm = shp_transform(to_utm.transform, polygon_wgs84)
   - Build grid in UTM metres, convert each point back to WGS84 for output.

B. RASTER SAMPLING (rasterio.sample):
   - A raster can be in ANY CRS. ALWAYS read src.crs and reproject coordinates to match.
   - NEVER pass raw lon/lat to src.sample() without checking the raster CRS first.
   - Correct pattern:
       from pyproj import Transformer
       with rasterio.open(raster_path) as src:
           t = Transformer.from_crs('EPSG:4326', src.crs, always_xy=True)
           coords_raster = [t.transform(lon, lat) for lon, lat in coords_wgs84]
           values = list(src.sample(coords_raster))

C. OUTPUT CRS: always return coordinates as WGS84 (lon, lat) in output files
   unless the user explicitly asked for a different CRS.

D. DISTANCE / AREA: always reproject to UTM before computing — never use
   shapely .distance() or .area directly on WGS84 geometries for metric results.

FORMAT-SPECIFIC GUIDANCE:
- KMZ files: use zipfile to extract the .kml inside, then parse with lxml
- HTML map output: write a self-contained HTML file with Leaflet.js CDN,
  embed data as JS variables, include OpenStreetMap tiles, auto-fit bounds
- PNG/JPG output: use matplotlib, save with plt.savefig(output_path, dpi=150, bbox_inches='tight')
- GeoJSON output: use json.dump with a FeatureCollection structure
- Shapefile output: use geopandas .to_file(output_path, driver='ESRI Shapefile')
- KML output: build XML with lxml.etree
- TIF output: use rasterio to write with proper CRS, transform, nodata
- CSV output: use pandas .to_csv() or csv.writer
- XLSX output: use openpyxl or pandas .to_excel()
"""


def run(step, plan_context: dict, llm) -> str:
    """
    Generate Python code for a step.

    Args:
        step: Step object
        plan_context: {
            'task': full task description,
            'previous_steps': list of {name, description, code, outputs},
            'parameters': dict of user params,
        }
        llm: LLMClient

    Returns: Python code string
    """
    prompt = _build_prompt(step, plan_context)
    raw = llm.generate(prompt, system=SYSTEM)
    return _extract_code(raw)


def _build_prompt(step, plan_context: dict) -> str:
    parts = [GEO_LIBRARIES_CONTEXT]

    # Parameters
    params = plan_context.get("parameters", {})
    if params:
        parts.append("\nPARAMETERS:")
        for k, v in params.items():
            parts.append(f"  {k} = {v}")

    # Previous steps context
    prev = plan_context.get("previous_steps", [])
    if prev:
        parts.append("\nPREVIOUS STEPS (already completed):")
        for p in prev:
            parts.append(f"  Step '{p['name']}': {p['description']}")
            parts.append(f"    Outputs: {p['outputs']}")
            if p.get("code"):
                # Show last 10 lines of code for format awareness
                code_lines = p["code"].strip().split("\n")
                snippet = "\n    ".join(code_lines[-10:])
                parts.append(f"    Code (last lines):\n    {snippet}")

    # Current step
    parts.append(f"\nCURRENT STEP: {step.name}")
    parts.append(f"  Description: {step.description}")
    parts.append(f"  Input files: {step.inputs}")
    parts.append(f"  Expected output files: {step.outputs}")

    parts.append("\nWrite the Python code. Remember INPUT_DIR and OUTPUT_DIR are already defined.")
    return "\n".join(parts)


def _extract_code(text: str) -> str:
    """Extract Python code from LLM output."""
    m = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # If no fences, try to find code that starts with import
    lines = text.strip().split("\n")
    code_lines = []
    started = False
    for line in lines:
        if line.strip().startswith(("import ", "from ", "#", "INPUT_DIR", "OUTPUT_DIR")):
            started = True
        if started:
            code_lines.append(line)
    if code_lines:
        return "\n".join(code_lines)
    return text.strip()
