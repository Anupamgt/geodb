"""
Knowledge Loader — loads relevant code patterns from .md files
for injection into agent system prompts.
"""
import os
from geodb.agent_factory.config import KNOWLEDGE_DIR


# Maps keywords/operations to knowledge files
KNOWLEDGE_MAP = {
    # Libraries
    "rasterio":    "libraries/rasterio.md",
    "shapely":     "libraries/shapely.md",
    "geopandas":   "libraries/geopandas.md",
    "openpyxl":    "libraries/openpyxl.md",
    "lxml_kml":    "libraries/lxml_kml.md",
    "pyproj":      "libraries/pyproj.md",
    "matplotlib":  "libraries/matplotlib.md",
    "shapefile_writing": "libraries/shapefile_writing.md",
    # Operations
    "dem_sampling":     "operations/dem_sampling.md",
    "kml_parsing":      "operations/kml_parsing.md",
    "grid_generation":  "operations/grid_generation.md",
    "crs_transform":    "operations/crs_transform.md",
    "raster_clip":      "operations/raster_clip.md",
    "profile_extraction": "operations/profile_extraction.md",
    "contour_extract":  "operations/contour_extract.md",
    "geometry_metrics": "operations/geometry_metrics.md",
}

# Maps transformation types to required knowledge
TRANSFORM_KNOWLEDGE = {
    "profile_extraction":           ["kml_parsing", "pyproj", "rasterio", "dem_sampling", "openpyxl"],
    "elevation_sampling_along_line": ["kml_parsing", "pyproj", "rasterio", "dem_sampling", "openpyxl"],
    "grid_sampling":                ["kml_parsing", "pyproj", "grid_generation", "rasterio", "dem_sampling", "openpyxl"],
    "point_sampling":               ["kml_parsing", "rasterio", "dem_sampling", "openpyxl"],
    "geometry_measurement":         ["kml_parsing", "pyproj", "geometry_metrics", "openpyxl"],
    "coordinate_extraction":        ["kml_parsing", "openpyxl"],
    "raster_clip":                  ["kml_parsing", "rasterio", "raster_clip"],
    "raster_processing":            ["rasterio"],
    "contour_extraction":           ["rasterio", "contour_extract"],
    "vector_processing":            ["kml_parsing", "geopandas"],
    "format_conversion":            ["kml_parsing", "geopandas", "shapefile_writing"],
    "visualization":                ["kml_parsing", "rasterio", "matplotlib"],
    "tabular_extraction":           ["kml_parsing", "openpyxl"],
}


def load_for_task(transformation_type: str, extra_keys: list = None) -> dict:
    """
    Load all relevant knowledge for a transformation type.
    Returns {key: content_string}.
    """
    keys = TRANSFORM_KNOWLEDGE.get(transformation_type, [])
    if extra_keys:
        keys = list(set(keys + extra_keys))

    result = {}
    for key in keys:
        content = load_one(key)
        if content:
            result[key] = content
    return result


def load_one(key: str) -> str:
    """Load a single knowledge file by key."""
    rel_path = KNOWLEDGE_MAP.get(key, "")
    if not rel_path:
        return ""
    full_path = os.path.join(KNOWLEDGE_DIR, rel_path)
    if os.path.isfile(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def load_or_generate(transformation_type: str, input_infos: list,
                      output_format: str, task_description: str,
                      extra_keys: list = None, verbose: bool = False) -> dict:
    """
    Smart knowledge loader: tries pre-built → auto-generated → fallback.

    1. Try loading pre-built knowledge (existing .md files)
    2. If empty and cloud LLM is available, auto-generate (Option B)
    3. If still empty, return fallback hints (Option C)

    Args:
        transformation_type: inferred transformation type
        input_infos: inspected input file dicts
        output_format: target output format (e.g. "csv", "geojson")
        task_description: the user's task
        extra_keys: additional knowledge keys to load
        verbose: print status messages

    Returns: {key: content_string}
    """
    # Step 1: Try pre-built knowledge
    result = load_for_task(transformation_type, extra_keys)

    if result:
        return result

    # Step 2: Try auto-generation with cloud LLM (Option B)
    try:
        from geodb.agent_factory.knowledge.auto_generator import (
            generate_knowledge, has_cached
        )
        from geodb.agent_factory.llm_cloud_client import CloudLLMClient

        # Determine the primary input format
        file_format = ""
        for info in input_infos:
            fmt = info.get("file_format", info.get("type", ""))
            if fmt:
                file_format = fmt
                break

        if file_format:
            # Check cache first (no API call needed)
            if has_cached(file_format, transformation_type):
                if verbose:
                    print(f"  📚 Using cached auto-generated knowledge for .{file_format}")
                from geodb.agent_factory.knowledge.auto_generator import _load_cached
                cached = _load_cached(file_format, transformation_type)
                if cached:
                    result["auto_generated"] = cached
                    return result

            # Try cloud LLM
            try:
                cloud = CloudLLMClient()
                if cloud.is_available():
                    if verbose:
                        print(f"  🌐 Generating knowledge for .{file_format} via cloud LLM…")
                    knowledge = generate_knowledge(
                        file_format, transformation_type,
                        task_description, cloud
                    )
                    if knowledge:
                        result["auto_generated"] = knowledge
                        if verbose:
                            print(f"  ✅ Knowledge generated and cached for .{file_format}")
                        return result
            except (ValueError, ConnectionError) as e:
                if verbose:
                    print(f"  ⚠️  Cloud LLM unavailable: {e}")

    except ImportError:
        pass  # cloud client not installed, skip to fallback

    # Step 3: Fallback hints (Option C)
    try:
        from geodb.agent_factory.knowledge.fallback import build_fallback_knowledge
        fallback = build_fallback_knowledge(
            input_infos, output_format, transformation_type
        )
        if fallback:
            result["fallback_hints"] = fallback
            if verbose:
                print(f"  📋 Using fallback knowledge hints")
    except ImportError:
        pass

    return result


def list_available() -> list:
    """List all available knowledge keys."""
    return sorted(KNOWLEDGE_MAP.keys())
