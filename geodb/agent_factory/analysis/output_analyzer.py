"""
Output Analyzer — reverse-engineers the example output to understand
what transformation was applied to the input.
"""
import json
import os
from geodb.agent_factory.analysis.file_inspector import inspect


def analyze_output(output_info: dict) -> dict:
    """
    Deeply analyze an example output file to understand its structure.
    Returns a dict describing the output pattern.
    """
    analysis = {
        "format": output_info.get("type", "unknown"),
        "structure": {},
        "patterns": [],
        "derived_params": {},
    }

    fmt = output_info.get("file_format", output_info.get("type", ""))

    if fmt in ("csv", "excel", "xlsx", "xls"):
        analysis["structure"] = _analyze_tabular(output_info)
    elif fmt in ("geojson",):
        analysis["structure"] = _analyze_geojson(output_info)
    elif fmt in ("geotiff", "tif", "tiff"):
        analysis["structure"] = _analyze_raster(output_info)
    elif fmt in ("kml", "kmz"):
        analysis["structure"] = _analyze_kml(output_info)
    else:
        analysis["structure"] = {"type": fmt, "raw": True}

    return analysis


def _analyze_tabular(info: dict) -> dict:
    """Analyze CSV or Excel output structure."""
    columns = info.get("columns", [])
    col_info = info.get("column_info", {})
    sample = info.get("sample_rows", [])
    rows = info.get("rows", 0)

    result = {
        "type": "tabular",
        "row_count": rows,
        "column_count": len(columns),
        "columns": [],
    }

    for col in columns:
        ci = col_info.get(col, {})
        col_desc = {
            "name": col,
            "is_numeric": ci.get("is_numeric", False),
        }

        if ci.get("is_numeric"):
            col_desc["min"] = ci.get("min")
            col_desc["max"] = ci.get("max")
            col_desc["mean"] = ci.get("mean")
            col_desc["monotonic"] = ci.get("monotonic_increasing", False)
            col_desc["typical_interval"] = ci.get("typical_interval")

            # Classify column role
            name_lower = col.lower()
            if name_lower in ("lat", "latitude", "y", "lat_y"):
                col_desc["role"] = "latitude"
            elif name_lower in ("lon", "lng", "longitude", "x", "lon_x"):
                col_desc["role"] = "longitude"
            elif "height" in name_lower or "elev" in name_lower or "alt" in name_lower or "z" in name_lower:
                col_desc["role"] = "elevation"
            elif "dist" in name_lower:
                col_desc["role"] = "distance"
                if col_desc.get("monotonic"):
                    col_desc["pattern"] = "cumulative_distance"
            elif "area" in name_lower:
                col_desc["role"] = "area"
            elif "slope" in name_lower:
                col_desc["role"] = "slope"
            elif "aspect" in name_lower:
                col_desc["role"] = "aspect"
            elif "perim" in name_lower:
                col_desc["role"] = "perimeter"
            elif "id" in name_lower or "point" in name_lower or "index" in name_lower:
                col_desc["role"] = "identifier"
                # Check if sequential
                if ci.get("min") is not None and ci.get("max") is not None:
                    if abs(ci["max"] - ci["min"] - (rows - 1)) < 2:
                        col_desc["pattern"] = "sequential"
            else:
                col_desc["role"] = "value"
        else:
            name_lower = col.lower()
            if "name" in name_lower or "label" in name_lower:
                col_desc["role"] = "label"
            else:
                col_desc["role"] = "text"

        result["columns"].append(col_desc)

    # Derive parameters from patterns
    params = {}

    # Spacing detection
    dist_cols = [c for c in result["columns"]
                 if c.get("role") == "distance" and c.get("typical_interval")]
    if dist_cols:
        interval = dist_cols[0]["typical_interval"]
        params["sampling_interval_m"] = round(interval, 1)
        total_dist = dist_cols[0].get("max", 0) - dist_cols[0].get("min", 0)
        params["total_length_m"] = round(total_dist, 1)

    # Grid detection
    lat_cols = [c for c in result["columns"] if c.get("role") == "latitude"]
    lon_cols = [c for c in result["columns"] if c.get("role") == "longitude"]
    if lat_cols and lon_cols and rows > 10:
        # Check if points form a grid pattern
        lat_vals = set()
        lon_vals = set()
        for s in sample:
            lat_key = lat_cols[0]["name"]
            lon_key = lon_cols[0]["name"]
            try:
                lat_vals.add(round(float(s.get(lat_key, 0)), 5))
                lon_vals.add(round(float(s.get(lon_key, 0)), 5))
            except (ValueError, TypeError):
                pass
        if len(lat_vals) > 1 and len(lon_vals) > 1:
            if len(lat_vals) * len(lon_vals) > rows * 0.5:
                params["pattern"] = "grid"
            else:
                params["pattern"] = "profile_line"

    result["derived_params"] = params
    return result


def _analyze_geojson(info: dict) -> dict:
    return {
        "type": "geojson",
        "feature_count": info.get("feature_count", 0),
        "geometry_types": info.get("geometry_types", {}),
        "properties": info.get("properties", []),
    }


def _analyze_raster(info: dict) -> dict:
    return {
        "type": "raster",
        "bands": info.get("bands"),
        "width": info.get("width"),
        "height": info.get("height"),
        "dtype": info.get("dtype"),
        "crs": info.get("crs"),
        "stats": info.get("stats", {}),
        "data_class": info.get("data_class", "unknown"),
    }


def _analyze_kml(info: dict) -> dict:
    return {
        "type": "kml",
        "feature_count": info.get("feature_count", 0),
        "geometry_types": info.get("geometry_types", {}),
    }


def format_analysis_for_prompt(input_infos: list, output_info: dict,
                                output_analysis: dict) -> str:
    """Format the analysis as text for the LLM prompt."""
    lines = ["EXAMPLE INPUT FILES:"]
    for inp in input_infos:
        lines.append(f"  File: {inp['name']} ({inp.get('file_format', inp['type'])})")
        if inp.get("feature_count"):
            lines.append(f"    Features: {inp['feature_count']}, Types: {inp.get('geometry_types', {})}")
        if inp.get("bounds"):
            lines.append(f"    Bounds: {inp['bounds']}")
        if inp.get("vertex_count"):
            lines.append(f"    Vertices: {inp['vertex_count']}")
        if inp.get("bands"):
            lines.append(f"    Bands: {inp['bands']}, Resolution: {inp.get('resolution')}, "
                        f"dtype: {inp.get('dtype')}")
        if inp.get("stats"):
            s = inp["stats"]
            lines.append(f"    Values: min={s.get('min')}, max={s.get('max')}, mean={s.get('mean')}")
        if inp.get("data_class"):
            lines.append(f"    Data class: {inp['data_class']}")

    lines.append(f"\nEXAMPLE OUTPUT FILE: {output_info['name']}")
    struct = output_analysis.get("structure", {})

    if struct.get("type") == "tabular":
        lines.append(f"  Rows: {struct['row_count']}, Columns: {struct['column_count']}")
        lines.append(f"  Column details:")
        for col in struct.get("columns", []):
            desc = f"    - {col['name']}: role={col.get('role','?')}"
            if col.get("is_numeric"):
                desc += f", range=[{col.get('min')}, {col.get('max')}]"
                if col.get("mean"):
                    desc += f", mean={col['mean']:.2f}"
            if col.get("pattern"):
                desc += f", pattern={col['pattern']}"
            if col.get("monotonic"):
                desc += ", monotonically increasing"
            if col.get("typical_interval"):
                desc += f", interval≈{col['typical_interval']:.1f}"
            lines.append(desc)

        params = struct.get("derived_params", {})
        if params:
            lines.append(f"  Derived parameters: {json.dumps(params)}")

    elif struct.get("type") == "geojson":
        lines.append(f"  Features: {struct.get('feature_count')}")
        lines.append(f"  Geometry types: {struct.get('geometry_types')}")
        lines.append(f"  Properties: {struct.get('properties')}")

    elif struct.get("type") == "raster":
        lines.append(f"  Size: {struct.get('width')}x{struct.get('height')}, "
                     f"Bands: {struct.get('bands')}")
        lines.append(f"  dtype: {struct.get('dtype')}, class: {struct.get('data_class')}")

    # Sample data
    sample = output_info.get("sample_rows", [])
    if sample:
        lines.append(f"  Sample data (first {min(len(sample), 5)} rows):")
        for row in sample[:5]:
            lines.append(f"    {json.dumps(row, default=str)}")

    return "\n".join(lines)
