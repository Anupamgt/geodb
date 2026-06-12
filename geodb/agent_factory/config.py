"""
Configuration for the Agent Factory system.
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))
AGENTS_DIR = os.path.join(PROJECT_DIR, "agents")
SANDBOX_ROOT = os.path.join(PROJECT_DIR, ".sandbox")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")

# Shared config file written by `python -m geodb.transform config`
_CONFIG_FILE = os.path.join(PROJECT_DIR, ".geodb_config.json")

def _saved() -> dict:
    try:
        with open(_CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _get(key, *env_vars, default=""):
    for var in env_vars:
        val = os.environ.get(var)
        if val:
            return val
    return _saved().get(key) or default

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME = os.environ.get("GEODB_MODEL", "qwen2.5-coder:7b")
LLM_TIMEOUT = 120
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 6000

CLOUD_PROVIDER = _get("cloud_provider", "GEODB_CLOUD_PROVIDER", default="openai")
CLOUD_API_KEY  = _get("cloud_api_key",  "GEODB_CLOUD_API_KEY",
                                         "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
CLOUD_MODEL    = _get("cloud_model",    "GEODB_CLOUD_MODEL",   default="gpt-4o-mini")
CLOUD_BASE_URL = _get("cloud_base_url", "GEODB_CLOUD_BASE_URL", default="")
CLOUD_TIMEOUT  = int(os.environ.get("GEODB_CLOUD_TIMEOUT", "60"))

STEP_TIMEOUT = 180
MAX_CREATE_RETRIES = 3
MAX_RUN_RETRIES = 2

ALLOWED_IMPORTS = {
    "rasterio", "rasterio.warp", "rasterio.mask", "rasterio.features",
    "rasterio.transform", "rasterio.crs", "rasterio.merge", "rasterio.windows",
    "shapely", "shapely.geometry", "shapely.ops", "shapely.affinity",
    "shapely.validation", "shapely.wkt",
    "geopandas", "fiona", "pyproj",
    "numpy", "np", "pandas", "pd",
    "scipy", "scipy.interpolate", "scipy.ndimage", "scipy.spatial",
    "openpyxl", "xlsxwriter", "csv",
    "matplotlib", "matplotlib.pyplot", "matplotlib.colors",
    "matplotlib.patches", "matplotlib.cm", "matplotlib.figure",
    "PIL", "PIL.Image",
    "lxml", "lxml.etree",
    "math", "json", "os", "os.path", "pathlib",
    "datetime", "time", "re", "glob", "sys",
    "collections", "itertools", "functools", "copy",
    "warnings", "io", "struct",
    "zipfile", "tempfile", "shutil", "hashlib",
    "typing",
}

BLOCKED_PATTERNS = [
    "subprocess", "os.system(", "os.popen(", "os.exec",
    "shutil.rmtree",
    "requests.", "urllib.", "http.client", "socket.",
    "ftplib", "smtplib",
    "eval(", "exec(", "compile(", "__import__(",
    "importlib.import",
]
