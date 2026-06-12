"""
Agent 5 — Visualizer
Takes: step output files + metadata + viz_hint
Produces: self-contained interactive HTML (Leaflet maps + Plotly charts)
Also produces a terminal-friendly text summary.
"""
import json
import os
import re
from geodb.transform.config import VIZ_CDN


SYSTEM = """\
You are a geospatial data visualization expert. You generate a single
self-contained HTML file with interactive visualizations.

LIBRARIES (loaded via CDN — do NOT import anything else):
- Leaflet 1.9.4 for maps (markers, polygons, polylines, heatmaps, layer controls)
- Plotly.js 2.27 for charts (histograms, scatter, line, bar, 3D surface)

OUTPUT: Only the complete HTML inside ```html``` fences. No commentary.

RULES:
- Fully self-contained: inline CSS, inline JS, CDN script tags, embedded data
- ALL data must be embedded as const variables in a <script> tag
- Use a clean dark professional theme (#1a1a2e background, #e0e0e0 text)
- Add a header bar with: step name, key stats
- Use a TAB layout for multiple visualizations:
  <div class="tabs"> with buttons, each tab shows a different viz
- For maps: Leaflet, auto-fit bounds to data, add scale control
- For charts: Plotly, interactive (hover, zoom, pan, download PNG button)
- For tables: sortable columns (click header to sort), scrollable, search box
- Color scales: use viridis-like gradient for numeric data on maps
- Make responsive: width 100%, height auto or vh-based
- For points on map: if >500 points, use CircleMarkers (radius 4-6), not full Markers
- For polygons: fill with semi-transparent color, show area in popup
- Include a data summary panel showing key statistics

TEMPLATE STRUCTURE:
<!DOCTYPE html>
<html>
<head>
    <title>Step N: name</title>
    <link rel="stylesheet" href="LEAFLET_CSS_CDN"/>
    <script src="LEAFLET_JS_CDN"></script>
    <script src="PLOTLY_JS_CDN"></script>
    <style>
        /* dark theme, tabs, responsive layout */
    </style>
</head>
<body>
    <div class="header">...</div>
    <div class="tabs">...</div>
    <div class="tab-content" id="tab-map">...</div>
    <div class="tab-content" id="tab-chart">...</div>
    <div class="tab-content" id="tab-table">...</div>
    <script>
        const DATA = [...];  // embedded data
        // map setup, chart setup, table setup, tab switching
    </script>
</body>
</html>
"""


def run(step, output_meta: dict, llm) -> dict:
    """
    Generate visualization for a step's output.

    Args:
        step: Step object (has name, description, viz_hint, outputs)
        output_meta: { filename: { type, rows, columns, stats, sample, ... } }
        llm: LLMClient

    Returns:
        { html: str, summary: str }
    """
    # Build data summary for the LLM
    summary_text = _build_data_summary(step, output_meta)

    # Also build terminal summary
    terminal_summary = _build_terminal_summary(step, output_meta)

    prompt = _build_prompt(step, output_meta, summary_text)
    raw = llm.generate(prompt, system=SYSTEM, max_tokens=8192)
    html = _extract_html(raw)

    # Inject CDN URLs if the LLM used placeholders
    html = _inject_cdns(html)

    return {
        "html": html,
        "summary": terminal_summary,
    }


def _build_prompt(step, output_meta: dict, summary: str) -> str:
    parts = [
        f"STEP: {step.id}. {step.name}",
        f"DESCRIPTION: {step.description}",
        f"VIZ HINT: {step.viz_hint}",
        "",
        "OUTPUT FILES AND DATA:",
        summary,
        "",
        "CDN URLs to use:",
        f"  Leaflet CSS: {VIZ_CDN['leaflet_css']}",
        f"  Leaflet JS:  {VIZ_CDN['leaflet_js']}",
        f"  Plotly JS:   {VIZ_CDN['plotly_js']}",
        "",
        "Generate the interactive HTML visualization.",
    ]
    return "\n".join(parts)


def _build_data_summary(step, output_meta: dict) -> str:
    """Build a text summary of output data for the LLM prompt."""
    parts = []
    for fname, meta in output_meta.items():
        ftype = meta.get("type", meta.get("extension", "unknown"))
        parts.append(f"\nFile: {fname} (type: {ftype})")

        if ftype == "csv":
            parts.append(f"  Rows: {meta.get('rows', '?')}")
            parts.append(f"  Columns: {meta.get('columns', [])}")
            parts.append(f"  Has lat/lon: {meta.get('has_latlon', False)}")
            stats = meta.get("numeric_stats", {})
            if stats:
                parts.append("  Numeric stats:")
                for col, s in list(stats.items())[:8]:
                    parts.append(f"    {col}: min={s['min']:.4f}, max={s['max']:.4f}, "
                               f"mean={s['mean']:.4f}")
            sample = meta.get("sample_rows", [])
            if sample:
                parts.append(f"  Sample data (first {len(sample)} rows):")
                parts.append(f"  {json.dumps(sample[:10], default=str)}")

        elif ftype == "geojson":
            parts.append(f"  Features: {meta.get('feature_count', '?')}")
            parts.append(f"  Geometry types: {meta.get('geometry_types', [])}")
            parts.append(f"  Bounds: {meta.get('bounds', [])}")
            parts.append(f"  Properties: {meta.get('properties', [])}")
            sample = meta.get("sample_features", [])
            if sample:
                parts.append(f"  Sample features (GeoJSON):")
                parts.append(f"  {json.dumps(sample[:3], default=str)[:2000]}")

        elif ftype in ("tif", "tiff"):
            parts.append(f"  Size: {meta.get('width', '?')}x{meta.get('height', '?')}")
            parts.append(f"  Bands: {meta.get('bands', '?')}")
            parts.append(f"  CRS: {meta.get('crs', '?')}")
            parts.append(f"  Bounds: {meta.get('bounds', [])}")
            s = meta.get("stats", {})
            if s:
                parts.append(f"  Values: min={s.get('min')}, max={s.get('max')}, "
                           f"mean={s.get('mean')}")

        elif ftype in ("excel", "xlsx"):
            parts.append(f"  Rows: {meta.get('rows', '?')}")
            parts.append(f"  Columns: {meta.get('columns', [])}")

    return "\n".join(parts)


def _build_terminal_summary(step, output_meta: dict) -> str:
    """Build a compact terminal-friendly summary."""
    lines = []
    for fname, meta in output_meta.items():
        ftype = meta.get("type", "?")
        size = meta.get("size_bytes", 0)
        size_str = f"{size / 1024:.1f} KB" if size < 1e6 else f"{size / 1e6:.1f} MB"

        line = f"    {fname} ({ftype}, {size_str})"

        if ftype == "csv":
            line += f" — {meta.get('rows', '?')} rows, {len(meta.get('columns', []))} cols"
            stats = meta.get("numeric_stats", {})
            for col, s in list(stats.items())[:3]:
                line += f"\n      {col}: {s['min']:.2f} – {s['max']:.2f} (mean {s['mean']:.2f})"

        elif ftype == "geojson":
            line += f" — {meta.get('feature_count', '?')} features {meta.get('geometry_types', [])}"
            b = meta.get("bounds")
            if b:
                line += f"\n      bounds: [{b[0]:.4f}, {b[1]:.4f}, {b[2]:.4f}, {b[3]:.4f}]"

        elif ftype in ("tif", "tiff"):
            line += f" — {meta.get('width')}x{meta.get('height')}, {meta.get('bands')} bands"
            s = meta.get("stats", {})
            if s.get("min") is not None:
                line += f"\n      values: {s['min']:.2f} – {s['max']:.2f} (mean {s['mean']:.2f})"

        elif ftype in ("excel", "xlsx"):
            line += f" — {meta.get('rows', '?')} rows, cols: {meta.get('columns', [])}"

        lines.append(line)

    return "\n".join(lines) if lines else "    (no output files)"


def _extract_html(text: str) -> str:
    m = re.search(r'```html\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try to find <!DOCTYPE or <html
    m = re.search(r'(<!DOCTYPE.*</html>)', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()


def _inject_cdns(html: str) -> str:
    """Replace any placeholder CDN references with actual URLs."""
    for key, url in VIZ_CDN.items():
        html = html.replace(f"LEAFLET_CSS_CDN", VIZ_CDN["leaflet_css"])
        html = html.replace(f"LEAFLET_JS_CDN", VIZ_CDN["leaflet_js"])
        html = html.replace(f"PLOTLY_JS_CDN", VIZ_CDN["plotly_js"])
    return html


# ── Fallback visualizer (no LLM needed) ──────────────────────────────────────

def generate_fallback(step, output_meta: dict) -> dict:
    """
    Generate a simple HTML visualization without using the LLM.
    Used as backup if the LLM-generated viz fails.
    """
    html_parts = [
        f"<!DOCTYPE html><html><head><title>Step {step.id}: {step.name}</title>",
        f'<link rel="stylesheet" href="{VIZ_CDN["leaflet_css"]}"/>',
        f'<script src="{VIZ_CDN["leaflet_js"]}"></script>',
        f'<script src="{VIZ_CDN["plotly_js"]}"></script>',
        "<style>",
        "body{margin:0;background:#1a1a2e;color:#e0e0e0;font-family:sans-serif}",
        ".header{padding:16px 24px;background:#16213e;border-bottom:1px solid #333}",
        ".content{padding:24px}",
        "#map{height:400px;margin:16px 0;border-radius:8px}",
        "#chart{height:350px;margin:16px 0}",
        "table{width:100%;border-collapse:collapse;margin:16px 0}",
        "th,td{padding:8px 12px;border:1px solid #333;text-align:left}",
        "th{background:#16213e;cursor:pointer}",
        "tr:hover{background:#16213e}",
        "</style></head><body>",
        f'<div class="header"><h2>Step {step.id}: {step.name}</h2></div>',
        '<div class="content">',
    ]

    # Render each output file
    for fname, meta in output_meta.items():
        ftype = meta.get("type", "")

        if ftype == "csv" and meta.get("has_latlon"):
            # Map + table
            sample = meta.get("sample_rows", [])
            html_parts.append(f'<h3>{fname} — {meta.get("rows", 0)} rows</h3>')
            html_parts.append('<div id="map"></div>')
            html_parts.append(f'<script>const csvData={json.dumps(sample[:200])};')
            html_parts.append("""
var map=L.map('map');L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
var pts=[];csvData.forEach(function(r){
var lat=parseFloat(r.lat||r.latitude||r.y);
var lon=parseFloat(r.lon||r.lng||r.longitude||r.x);
if(!isNaN(lat)&&!isNaN(lon)){pts.push([lat,lon]);L.circleMarker([lat,lon],{radius:4,color:'#4fc3f7',fillOpacity:0.8}).addTo(map);}
});if(pts.length)map.fitBounds(pts);
</script>""")

        elif ftype == "geojson":
            sample = meta.get("sample_features", [])
            fc = {"type": "FeatureCollection", "features": sample[:100]}
            html_parts.append(f'<h3>{fname} — {meta.get("feature_count", 0)} features</h3>')
            html_parts.append('<div id="map"></div>')
            html_parts.append(f'<script>const geoData={json.dumps(fc)};')
            html_parts.append("""
var map=L.map('map');L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
var layer=L.geoJSON(geoData,{style:{color:'#4fc3f7',weight:2,fillOpacity:0.3}}).addTo(map);
map.fitBounds(layer.getBounds());
</script>""")

        # Table for CSV/Excel
        if ftype in ("csv", "excel", "xlsx"):
            cols = meta.get("columns", [])
            rows = meta.get("sample_rows", [])
            if cols and rows:
                html_parts.append(f'<h3>Data Preview (first {len(rows)} rows)</h3>')
                html_parts.append('<table><thead><tr>')
                for c in cols[:15]:
                    html_parts.append(f'<th>{c}</th>')
                html_parts.append('</tr></thead><tbody>')
                for row in rows[:30]:
                    html_parts.append('<tr>')
                    for c in cols[:15]:
                        v = row.get(c, "") if isinstance(row, dict) else ""
                        html_parts.append(f'<td>{v}</td>')
                    html_parts.append('</tr>')
                html_parts.append('</tbody></table>')

    html_parts.append('</div></body></html>')
    html = "\n".join(html_parts)

    return {
        "html": html,
        "summary": _build_terminal_summary(step, output_meta),
    }
