"""
Configuration for the geospatial transformation pipeline system.
"""
import json
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))
PIPELINES_DIR = os.path.join(PROJECT_DIR, "pipelines")
EXAMPLES_DIR = os.path.join(BASE_DIR, "examples")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
SANDBOX_ROOT = os.path.join(PROJECT_DIR, ".sandbox")

# ── Persistent config file (written by `python -m geodb.transform config`) ────
CONFIG_FILE = os.path.join(PROJECT_DIR, ".geodb_config.json")

def _load_saved() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(data: dict):
    """Merge data into the saved config file."""
    saved = _load_saved()
    saved.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(saved, f, indent=2)

def _get(key: str, *env_vars, default="") -> str:
    """Env var > saved config > default."""
    for var in env_vars:
        val = os.environ.get(var)
        if val:
            return val
    return _load_saved().get(key) or default

# ── LLM — local (Ollama) ──────────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME = os.environ.get("GEODB_MODEL", "qwen2.5-coder:7b")
LLM_TIMEOUT = 120
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 4096

# ── LLM — cloud API (OpenAI / Anthropic / compatible) ─────────────────────────
CLOUD_PROVIDER = _get("cloud_provider", "GEODB_CLOUD_PROVIDER", default="openai")
CLOUD_API_KEY  = _get("cloud_api_key",  "GEODB_CLOUD_API_KEY",
                                         "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
CLOUD_MODEL    = _get("cloud_model",    "GEODB_CLOUD_MODEL",   default="gpt-4o-mini")
CLOUD_BASE_URL = _get("cloud_base_url", "GEODB_CLOUD_BASE_URL", default="")
CLOUD_TIMEOUT  = int(os.environ.get("GEODB_CLOUD_TIMEOUT", "60"))

# ── Execution ─────────────────────────────────────────────────────────────────
STEP_TIMEOUT = 180          # seconds per step execution
MAX_CODER_RETRIES = 3       # coder ↔ verifier loops
MAX_FIXER_RETRIES = 2       # fixer attempts after runtime error
MAX_VIZ_RETRIES = 2         # visualizer regeneration attempts

# ── Sandbox safety ────────────────────────────────────────────────────────────
ALLOWED_IMPORTS = {
    # Geo
    "rasterio", "rasterio.warp", "rasterio.mask", "rasterio.features",
    "rasterio.transform", "rasterio.crs", "rasterio.merge", "rasterio.enums",
    "rasterio.io", "rasterio.plot", "rasterio.windows",
    "shapely", "shapely.geometry", "shapely.ops", "shapely.affinity",
    "shapely.validation", "shapely.wkt", "shapely.wkb",
    "geopandas", "fiona", "pyproj",
    # Data
    "numpy", "np", "pandas", "pd",
    "scipy", "scipy.interpolate", "scipy.ndimage", "scipy.spatial",
    # Output
    "openpyxl", "xlsxwriter", "csv",
    # Viz / image output
    "matplotlib", "matplotlib.pyplot", "matplotlib.colors",
    "matplotlib.patches", "matplotlib.collections", "matplotlib.cm",
    "matplotlib.figure", "matplotlib.ticker",
    "PIL", "PIL.Image",
    # Utilities
    "math", "json", "os", "os.path", "pathlib",
    "datetime", "time", "re", "glob", "sys",
    "collections", "itertools", "functools", "copy",
    "warnings", "traceback", "io", "struct",
    "zipfile", "tempfile", "shutil", "hashlib",
    "lxml", "lxml.etree",
    # Typing
    "typing",
}

BLOCKED_PATTERNS = [
    "subprocess", "os.system(", "os.popen(", "os.exec",
    "shutil.rmtree",
    "requests.", "urllib.", "http.client", "socket.",
    "ftplib", "smtplib", "telnetlib",
    "eval(", "exec(", "compile(", "__import__(",
    "importlib.import",
    "ctypes", "cffi",
]

# ── Geo context for prompts ───────────────────────────────────────────────────
GEO_LIBRARIES_CONTEXT = """\
AVAILABLE PYTHON LIBRARIES:
- rasterio: read/write GeoTIFF, sample raster values, warp/reproject, mask/clip
- shapely: geometry objects (Point, Polygon, LineString), operations (buffer, intersection, union)
- geopandas: GeoDataFrames, read/write GeoJSON/Shapefile/KML, spatial joins, CRS transforms
- fiona: low-level vector file I/O
- pyproj: CRS transformations, UTM zone detection
- numpy: arrays, math operations
- pandas: DataFrames, CSV/Excel I/O
- openpyxl: write Excel files with formatting
- scipy: interpolation, spatial analysis
- matplotlib / matplotlib.pyplot: render maps, charts, save as PNG/JPG/PDF
- PIL / PIL.Image: image manipulation
- lxml: XML/KML parsing
- zipfile: extract KMZ (zipped KML) files
- math, json, csv, os, pathlib: standard library

OUTPUT FORMAT RECIPES:
- HTML interactive map: write a self-contained .html file with embedded Leaflet.js + data as JSON.
  Use CDN links: https://unpkg.com/leaflet@1.9.4/dist/leaflet.js
  Embed data as `const data = [...]` in a <script> tag. No server needed.
- PNG/JPG static image: use matplotlib to plot, then plt.savefig(output_path, dpi=150, bbox_inches='tight')
- GeoTIFF: use rasterio.open(path, 'w', ...) with proper CRS, transform, dtype
- Shapefile: gdf.to_file(path, driver='ESRI Shapefile')
- GeoJSON: gdf.to_file(path, driver='GeoJSON')  or  json.dump(feature_collection, f)
- KML: write XML with lxml.etree
- CSV: df.to_csv(path, index=False)
- Excel: df.to_excel(path, index=False)

CODE CONVENTIONS:
- Input files are in the directory stored in variable INPUT_DIR
- Output files MUST be written to the directory stored in variable OUTPUT_DIR
- Use: input_path = os.path.join(INPUT_DIR, 'filename.ext')
- Use: output_path = os.path.join(OUTPUT_DIR, 'filename.ext')
- Always handle nodata/NaN values
- CRITICAL: Never call a helper function you haven't defined. Write all logic inline.

CRS RULES (follow exactly — CRS mismatches cause silent wrong results):
- METRIC GRID (e.g. 20m spacing): polygon is WGS84 → reproject to UTM → grid in metres
  → convert each point back to WGS84 for output. Never space a grid in degrees.
      zone = int((lon_c+180)/6)+1; utm_epsg = 32600+zone if lat_c>=0 else 32700+zone
      to_utm = Transformer.from_crs('EPSG:4326', utm_epsg, always_xy=True)
      to_wgs = Transformer.from_crs(utm_epsg, 'EPSG:4326', always_xy=True)
      poly_utm = shp_transform(to_utm.transform, polygon_wgs84)
- RASTER SAMPLING: ALWAYS reproject coords to raster's CRS before src.sample().
  Never assume raster is WGS84. Read src.crs and transform accordingly:
      t = Transformer.from_crs('EPSG:4326', src.crs, always_xy=True)
      coords_proj = [t.transform(lon, lat) for lon, lat in coords_wgs84]
      values = list(src.sample(coords_proj))
- OUTPUT: always write lon/lat as WGS84 in final files unless user specifies otherwise.
- DISTANCE/AREA: always use UTM; never compute on raw WGS84 geometries.
- For HTML map output, use this Leaflet template:
    <!DOCTYPE html><html><head>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    </head><body><div id="map" style="height:100vh"></div><script>
    const data = EMBEDDED_DATA_HERE;
    var map = L.map('map'); L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    // add layers, fit bounds
    </script></body></html>
- Print a summary of what was produced at the end
"""

# ── Viz CDN links ─────────────────────────────────────────────────────────────
VIZ_CDN = {
    "leaflet_css": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "leaflet_js": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "leaflet_heat": "https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js",
    "plotly_js": "https://cdn.plot.ly/plotly-2.27.0.min.js",
    "turf_js": "https://unpkg.com/@turf/turf@6/turf.min.js",
}
