"""
Format pipeline traces for terminal display or JSON export.
"""
import json

_PREFERRED_COLS = [
    "_year", "filename", "file_type", "file_path",
    "feature_count", "layer_names",
    "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy",
    "description", "tags", "band_count", "resolution_x",
    "temporal_start", "size_bytes",
]


def as_text(trace: dict, show_sql: bool = True) -> str:
    lines = []

    if trace.get("error"):
        lines.append(f"\n❌  {trace['error']}")
        last = trace["attempts"][-1] if trace.get("attempts") else {}
        if last.get("sql"):
            lines.append(f"    Last SQL: {last['sql']}")
        return "\n".join(lines)

    if show_sql and trace.get("final_sql"):
        lines.append(f"\n📝  SQL:\n    {trace['final_sql']}")

    loc = trace.get("location") or {}
    if loc.get("place"):
        lines.append(f"📍  {loc['place']}  ({loc['lon']}, {loc['lat']})  "
                      f"radius={loc.get('radius_km', '?')} km")

    res = trace.get("results") or {}
    rows = res.get("rows", [])
    lines.append(f"\n📊  {res.get('count', 0)} results  "
                 f"({res.get('shards', 0)} shard(s) searched)")

    if not rows:
        return "\n".join(lines)

    # Pick columns
    available = list(rows[0].keys())
    cols = [c for c in _PREFERRED_COLS if c in available]
    if not cols:
        cols = available[:8]

    # Compute widths
    widths = {}
    for c in cols:
        widths[c] = max(len(c), 6)
        for row in rows[:50]:
            widths[c] = max(widths[c], len(_t(row.get(c), 30)))

    hdr = " | ".join(f"{c:>{widths[c]}}" for c in cols)
    lines += ["", hdr, "-" * len(hdr)]

    for row in rows[:50]:
        lines.append(" | ".join(
            f"{_t(row.get(c), widths[c]):>{widths[c]}}" for c in cols
        ))

    if len(rows) > 50:
        lines.append(f"  … +{len(rows) - 50} more")

    # File-content summaries (from file_inspector)
    inspected = [r for r in rows if r.get("_content")]
    if inspected:
        lines.append("\n🔬  File contents:")
        for r in inspected:
            label = r.get("filename") or r.get("file_path") or f"id={r.get('id')}"
            lines.append(f"\n  ── {label} ──")
            lines.append(_format_content(r["_content"]))

    # Coverage / district info (from reverse_lookup)
    covered = [r for r in rows if r.get("_coverage")]
    if covered:
        lines.append("\n🗺   Coverage:")
        for r in covered:
            label = r.get("filename") or r.get("file_path") or f"id={r.get('id')}"
            lines.append(f"  ── {label} ──")
            lines.append(_format_coverage(r["_coverage"]))

    if res.get("errors"):
        lines.append(f"\n⚠️  Shard errors: {res['errors']}")

    return "\n".join(lines)


def as_json(trace: dict) -> str:
    out = {
        "query":    trace["query"],
        "location": trace.get("location"),
        "sql":      trace.get("final_sql"),
        "count":    (trace.get("results") or {}).get("count", 0),
        "rows":     (trace.get("results") or {}).get("rows", []),
        "error":    trace.get("error"),
    }
    return json.dumps(out, indent=2, default=str)


def _t(val, maxlen=30):
    s = "" if val is None else str(val)
    return s if len(s) <= maxlen else s[:maxlen - 1] + "…"


def _format_content(c: dict) -> str:
    if c.get("error"):
        return f"    ⚠️  {c['error']}"

    out = []
    kind = c.get("kind")

    if kind == "kml":
        out.append(f"    placemarks: {c.get('total_placemarks', 0)} "
                   f"(showing {c.get('shown_placemarks', 0)})")
        if c.get("folders"):
            out.append(f"    folders: {', '.join(c['folders'][:10])}")
        for pm in c.get("placemarks", []):
            name = pm.get("name") or "(unnamed)"
            geom = pm.get("geometry") or "?"
            cc = pm.get("coord_count", 0)
            fc = pm.get("first_coord")
            line = f"      • {name}  [{geom}, {cc} coords]"
            if fc:
                line += f"  first=({fc[0]:.5f}, {fc[1]:.5f})"
            out.append(line)
            if pm.get("description"):
                out.append(f"          {pm['description']}")

    elif kind == "tif":
        out.append(f"    {c.get('width')}×{c.get('height')} px, "
                   f"{c.get('band_count')} band(s), dtype={c.get('dtypes')}")
        out.append(f"    crs={c.get('crs')}  res={c.get('resolution')}  "
                   f"nodata={c.get('nodata')}")
        for b in c.get("bands", [])[:6]:
            line = f"      band {b['index']}"
            if b.get("description"):
                line += f" — {b['description']}"
            if "min" in b:
                line += f"  min={b['min']:.3g}  max={b['max']:.3g}  mean={b['mean']:.3g}"
            out.append(line)

    return "\n".join(out)


def _format_coverage(c: dict) -> str:
    if not c:
        return "    (no bbox)"
    out = []
    cx, cy = c.get("centre", (None, None))
    out.append(f"    centre: ({cx}, {cy})  ≈ {c.get('approx_area_km2')} km²")
    inside = c.get("districts_inside_bbox") or []
    if inside:
        out.append(f"    districts inside bbox: {', '.join(inside)}")
    nd = c.get("nearest_district") or {}
    if nd:
        out.append(f"    nearest district: {nd.get('name')} "
                   f"({nd.get('distance_km')} km from centre)")
    nearby = c.get("nearby_districts") or []
    if nearby:
        out.append("    nearby: " + ", ".join(f"{n} ({d}km)" for n, d in nearby))
    return "\n".join(out)
