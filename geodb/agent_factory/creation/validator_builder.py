"""
Validator Builder — creates validation rules from example output analysis.
"""
import os


def build_rules(output_info: dict, output_analysis: dict) -> list:
    """
    Generate validation rules from the example output.
    Returns list of rule dicts for runtime/validator.py.
    """
    rules = []
    struct = output_analysis.get("structure", {})
    fmt = output_info.get("file_format", output_info.get("type", ""))
    fname = output_info.get("name", "")
    ext = os.path.splitext(fname)[1].lower() if fname else ""

    # File existence
    if ext:
        rules.append({"check": "file_exists", "pattern": f"*{ext}"})
        rules.append({"check": "file_min_size", "file": f"*{ext}", "min_bytes": 100})

    if struct.get("type") == "tabular":
        columns = [c["name"] for c in struct.get("columns", [])]

        # Column check
        if columns:
            check = "excel_has_columns" if ext in (".xlsx", ".xls") else "csv_has_columns"
            rules.append({"check": check, "file": f"*{ext}", "columns": columns})

        # Row count minimum
        row_count = struct.get("row_count", 0)
        if row_count > 0:
            rules.append({"check": "row_count_min", "file": f"*{ext}", "min": max(1, row_count // 5)})

        # Per-column rules
        for col in struct.get("columns", []):
            if col.get("is_numeric") and col.get("role") not in ("identifier",):
                # Type check
                rules.append({
                    "check": "column_type",
                    "file": f"*{ext}",
                    "column": col["name"],
                    "type": "numeric",
                })

                # Range check for coordinates
                if col.get("role") == "latitude":
                    rules.append({
                        "check": "column_range",
                        "file": f"*{ext}",
                        "column": col["name"],
                        "min": -90, "max": 90,
                    })
                elif col.get("role") == "longitude":
                    rules.append({
                        "check": "column_range",
                        "file": f"*{ext}",
                        "column": col["name"],
                        "min": -180, "max": 180,
                    })

                # Monotonic check
                if col.get("monotonic"):
                    rules.append({
                        "check": "column_monotonic",
                        "file": f"*{ext}",
                        "column": col["name"],
                        "direction": "increasing",
                    })

    elif struct.get("type") == "geojson":
        rules.append({"check": "valid_geojson", "file": f"*{ext or '.geojson'}"})

    elif struct.get("type") == "raster":
        rules.append({"check": "valid_geotiff", "file": f"*{ext or '.tif'}"})

    return rules
