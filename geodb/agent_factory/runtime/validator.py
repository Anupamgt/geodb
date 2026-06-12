"""
Rule-based output validator — checks agent output files against declared rules.
No LLM needed.
"""
import json
import os


def validate(output_dir: str, rules: list) -> dict:
    """
    Validate output files against a list of rules.
    Returns { passed: bool, results: list[{rule, passed, detail}] }
    """
    results = []
    all_pass = True

    for rule in rules:
        check = rule.get("check", "")
        r = {"rule": rule, "passed": False, "detail": ""}

        try:
            if check == "file_exists":
                r = _check_file_exists(output_dir, rule)
            elif check == "file_min_size":
                r = _check_file_min_size(output_dir, rule)
            elif check == "file_contains":
                r = _check_file_contains(output_dir, rule)
            elif check == "excel_has_columns":
                r = _check_excel_columns(output_dir, rule)
            elif check == "csv_has_columns":
                r = _check_csv_columns(output_dir, rule)
            elif check == "column_type":
                r = _check_column_type(output_dir, rule)
            elif check == "column_range":
                r = _check_column_range(output_dir, rule)
            elif check == "row_count_min":
                r = _check_row_count(output_dir, rule)
            elif check == "column_monotonic":
                r = _check_monotonic(output_dir, rule)
            elif check == "valid_geojson":
                r = _check_valid_geojson(output_dir, rule)
            elif check == "valid_geotiff":
                r = _check_valid_geotiff(output_dir, rule)
            elif check == "valid_shapefile":
                r = _check_valid_shapefile(output_dir, rule)
            elif check == "no_errors_in_stdout":
                r = {"rule": rule, "passed": True, "detail": "skipped (runtime check)"}
            else:
                r = {"rule": rule, "passed": True, "detail": f"unknown check: {check}"}
        except Exception as e:
            r = {"rule": rule, "passed": False, "detail": f"error: {e}"}

        if not r["passed"]:
            all_pass = False
        results.append(r)

    return {"passed": all_pass, "results": results}


def _find_file(output_dir, pattern):
    """Find a file matching a pattern (exact name or glob)."""
    if "*" in pattern:
        import glob
        matches = glob.glob(os.path.join(output_dir, pattern))
        return matches[0] if matches else None
    path = os.path.join(output_dir, pattern)
    return path if os.path.isfile(path) else None


def _check_file_exists(output_dir, rule):
    pattern = rule.get("file", rule.get("pattern", "*"))
    path = _find_file(output_dir, pattern)
    if path:
        return {"rule": rule, "passed": True, "detail": f"found: {os.path.basename(path)}"}
    return {"rule": rule, "passed": False, "detail": f"file not found: {pattern}"}


def _check_file_min_size(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    size = os.path.getsize(path)
    min_bytes = rule.get("min_bytes", 100)
    if size >= min_bytes:
        return {"rule": rule, "passed": True, "detail": f"size={size} >= {min_bytes}"}
    return {"rule": rule, "passed": False, "detail": f"size={size} < {min_bytes}"}


def _check_file_contains(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    text = rule.get("text", "")
    with open(path, "r", errors="ignore") as f:
        content = f.read()
    if text.lower() in content.lower():
        return {"rule": rule, "passed": True, "detail": f"contains '{text}'"}
    return {"rule": rule, "passed": False, "detail": f"does not contain '{text}'"}


def _check_excel_columns(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.xlsx"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    headers = [str(c.value).strip() if c.value else "" for c in next(ws.iter_rows(max_row=1))]
    wb.close()
    expected = rule.get("columns", [])
    missing = [c for c in expected if c not in headers]
    if not missing:
        return {"rule": rule, "passed": True, "detail": f"all columns present: {headers}"}
    return {"rule": rule, "passed": False, "detail": f"missing columns: {missing}, got: {headers}"}


def _check_csv_columns(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.csv"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    import csv
    with open(path, "r", encoding="utf-8-sig") as f:
        headers = next(csv.reader(f), [])
    expected = rule.get("columns", [])
    missing = [c for c in expected if c not in headers]
    if not missing:
        return {"rule": rule, "passed": True, "detail": f"columns present"}
    return {"rule": rule, "passed": False, "detail": f"missing: {missing}, got: {headers}"}


def _check_column_type(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.csv"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    col = rule.get("column", "")
    expected = rule.get("type", "numeric")
    if col not in df.columns:
        return {"rule": rule, "passed": False, "detail": f"column '{col}' not found"}
    if expected == "numeric":
        is_num = pd.to_numeric(df[col], errors="coerce").notna().mean() > 0.8
        return {"rule": rule, "passed": is_num, "detail": f"numeric ratio: {pd.to_numeric(df[col], errors='coerce').notna().mean():.2f}"}
    return {"rule": rule, "passed": True, "detail": "type check skipped"}


def _check_column_range(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.csv"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    df = pd.read_excel(path) if ext in (".xlsx", ".xls") else pd.read_csv(path)
    col = rule.get("column", "")
    if col not in df.columns:
        return {"rule": rule, "passed": False, "detail": f"column '{col}' not found"}
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    rmin, rmax = rule.get("min", float("-inf")), rule.get("max", float("inf"))
    actual_min, actual_max = vals.min(), vals.max()
    ok = actual_min >= rmin and actual_max <= rmax
    return {"rule": rule, "passed": ok,
            "detail": f"range [{actual_min:.4f}, {actual_max:.4f}] vs expected [{rmin}, {rmax}]"}


def _check_row_count(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.csv"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    df = pd.read_excel(path) if ext in (".xlsx", ".xls") else pd.read_csv(path)
    actual = len(df)
    minimum = rule.get("min", 1)
    ok = actual >= minimum
    return {"rule": rule, "passed": ok, "detail": f"rows={actual}, min={minimum}"}


def _check_monotonic(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.csv"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    df = pd.read_excel(path) if ext in (".xlsx", ".xls") else pd.read_csv(path)
    col = rule.get("column", "")
    if col not in df.columns:
        return {"rule": rule, "passed": False, "detail": f"column '{col}' not found"}
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    direction = rule.get("direction", "increasing")
    if direction == "increasing":
        ok = vals.is_monotonic_increasing
    else:
        ok = vals.is_monotonic_decreasing
    return {"rule": rule, "passed": ok, "detail": f"monotonic {direction}: {ok}"}


def _check_valid_geojson(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.geojson"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    with open(path) as f:
        data = json.load(f)
    has_features = "features" in data and len(data["features"]) > 0
    return {"rule": rule, "passed": has_features, "detail": f"features: {len(data.get('features', []))}"}


def _check_valid_geotiff(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.tif"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found"}
    import rasterio
    with rasterio.open(path) as src:
        ok = src.width > 0 and src.height > 0
    return {"rule": rule, "passed": ok, "detail": f"valid geotiff: {ok}"}


def _check_valid_shapefile(output_dir, rule):
    path = _find_file(output_dir, rule.get("file", "*.shp"))
    if not path:
        return {"rule": rule, "passed": False, "detail": "file not found: *.shp"}
    import geopandas as gpd
    gdf = gpd.read_file(path)
    ok = len(gdf) > 0
    # Check sidecar files exist
    base = os.path.splitext(path)[0]
    sidecars = [base + ext for ext in (".shx", ".dbf", ".prj")]
    missing = [s for s in sidecars if not os.path.isfile(s)]
    if missing:
        return {"rule": rule, "passed": False,
                "detail": f"missing sidecar files: {[os.path.basename(m) for m in missing]}"}
    return {"rule": rule, "passed": ok,
            "detail": f"valid shapefile: {len(gdf)} features"}
