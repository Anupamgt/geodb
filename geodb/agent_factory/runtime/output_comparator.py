"""
Output Comparator — compare agent output vs expected example output.
Returns similarity scores and specific differences.
"""
import os


def compare(actual_dir: str, expected_info: dict, actual_info: dict) -> dict:
    """
    Compare actual agent output against the expected example output.
    Both infos come from file_inspector.inspect().
    Returns { match: bool, score: float (0-1), details: list[str] }
    """
    details = []
    scores = []

    # Format match
    afmt = actual_info.get("file_format", actual_info.get("type", ""))
    efmt = expected_info.get("file_format", expected_info.get("type", ""))
    if afmt == efmt:
        scores.append(1.0)
        details.append(f"✓ Format match: {afmt}")
    else:
        scores.append(0.0)
        details.append(f"✗ Format mismatch: got {afmt}, expected {efmt}")

    # Tabular comparison
    if efmt in ("csv", "excel", "xlsx"):
        scores_t, details_t = _compare_tabular(actual_info, expected_info)
        scores.extend(scores_t)
        details.extend(details_t)

    elif efmt in ("geojson",):
        scores_t, details_t = _compare_geojson(actual_info, expected_info)
        scores.extend(scores_t)
        details.extend(details_t)

    elif efmt in ("geotiff", "tif"):
        scores_t, details_t = _compare_raster(actual_info, expected_info)
        scores.extend(scores_t)
        details.extend(details_t)

    overall = sum(scores) / len(scores) if scores else 0.0
    return {
        "match": overall >= 0.7,
        "score": round(overall, 3),
        "details": details,
    }


def _compare_tabular(actual, expected):
    scores = []
    details = []

    # Column names
    a_cols = set(actual.get("columns", []))
    e_cols = set(expected.get("columns", []))
    if a_cols == e_cols:
        scores.append(1.0)
        details.append(f"✓ Columns match: {sorted(e_cols)}")
    elif e_cols.issubset(a_cols):
        scores.append(0.8)
        details.append(f"~ Expected columns present, extra: {a_cols - e_cols}")
    else:
        missing = e_cols - a_cols
        scores.append(0.2)
        details.append(f"✗ Missing columns: {missing}")

    # Row count
    a_rows = actual.get("rows", 0)
    e_rows = expected.get("rows", 0)
    if e_rows > 0:
        ratio = min(a_rows, e_rows) / max(a_rows, e_rows) if max(a_rows, e_rows) > 0 else 0
        scores.append(ratio)
        details.append(f"{'✓' if ratio > 0.8 else '~'} Rows: {a_rows} vs expected {e_rows} ({ratio:.0%})")

    # Numeric column ranges
    a_ci = actual.get("column_info", {})
    e_ci = expected.get("column_info", {})
    for col in e_cols & a_cols:
        ai = a_ci.get(col, {})
        ei = e_ci.get(col, {})
        if ei.get("is_numeric") and ai.get("is_numeric"):
            if ei.get("min") is not None and ai.get("min") is not None:
                e_range = (ei.get("max", 0) - ei.get("min", 0)) or 1
                diff = abs(ai.get("min", 0) - ei.get("min", 0)) / abs(e_range)
                s = max(0, 1 - diff)
                scores.append(s)
                if s > 0.8:
                    details.append(f"✓ {col} range similar")
                else:
                    details.append(f"~ {col}: got [{ai.get('min'):.2f},{ai.get('max'):.2f}] "
                                 f"vs [{ei.get('min'):.2f},{ei.get('max'):.2f}]")

    return scores, details


def _compare_geojson(actual, expected):
    scores = []
    details = []

    a_fc = actual.get("feature_count", 0)
    e_fc = expected.get("feature_count", 0)
    if e_fc > 0:
        ratio = min(a_fc, e_fc) / max(a_fc, e_fc) if max(a_fc, e_fc) > 0 else 0
        scores.append(ratio)
        details.append(f"{'✓' if ratio > 0.8 else '~'} Features: {a_fc} vs {e_fc}")

    a_gt = set(actual.get("geometry_types", {}).keys() if isinstance(actual.get("geometry_types"), dict) else actual.get("geometry_types", []))
    e_gt = set(expected.get("geometry_types", {}).keys() if isinstance(expected.get("geometry_types"), dict) else expected.get("geometry_types", []))
    if a_gt == e_gt:
        scores.append(1.0)
        details.append(f"✓ Geometry types match: {e_gt}")
    else:
        scores.append(0.3)
        details.append(f"✗ Geometry types: got {a_gt}, expected {e_gt}")

    return scores, details


def _compare_raster(actual, expected):
    scores = []
    details = []

    for key in ("bands", "dtype"):
        a_val = actual.get(key)
        e_val = expected.get(key)
        if a_val == e_val:
            scores.append(1.0)
            details.append(f"✓ {key} match: {e_val}")
        else:
            scores.append(0.0)
            details.append(f"✗ {key}: got {a_val}, expected {e_val}")

    a_stats = actual.get("stats", {})
    e_stats = expected.get("stats", {})
    if e_stats.get("min") is not None and a_stats.get("min") is not None:
        e_range = (e_stats["max"] - e_stats["min"]) or 1
        diff = abs(a_stats["min"] - e_stats["min"]) / abs(e_range)
        s = max(0, 1 - diff)
        scores.append(s)
        details.append(f"{'✓' if s > 0.8 else '~'} Value range similar")

    return scores, details
