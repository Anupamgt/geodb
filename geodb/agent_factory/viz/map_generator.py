"""
Map Generator — creates interactive HTML maps.
Style: black background, gray boundaries, yellow data overlay.
Region: India-focused (auto-fits to data bounds within India).
"""
import json
import os
import webbrowser
import tempfile

from geodb.agent_factory.viz.data_extractor import extract_from_outputs


# India bounding box for default view
INDIA_CENTER = [22.5, 82.0]
INDIA_ZOOM = 5
INDIA_BOUNDS = [[6.0, 68.0], [37.0, 98.0]]


def show_step_map(output_paths: dict, step_name: str = "",
                  output_dir: str = None) -> str:
    """
    Extract geo data from step outputs and open an interactive map.

    Args:
        output_paths: {filename: full_path} from step execution
        step_name: label for the map title
        output_dir: where to save the HTML (temp if None)

    Returns: path to the HTML file (empty string if no data)
    """
    geo_data = extract_from_outputs(output_paths)

    if not geo_data["has_data"]:
        return ""

    html = _build_map_html(geo_data, step_name)

    # Save
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        safe_name = step_name.replace(" ", "_").replace("/", "_")[:30] if step_name else "map"
        map_path = os.path.join(output_dir, f"map_{safe_name}.html")
    else:
        fd, map_path = tempfile.mkstemp(suffix=".html", prefix="map_")
        os.close(fd)

    with open(map_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Open in browser
    try:
        webbrowser.open(f"file://{os.path.abspath(map_path)}")
    except Exception:
        pass

    return map_path


def _build_map_html(geo_data: dict, title: str) -> str:
    """Build the full self-contained HTML map."""

    points_json = json.dumps(geo_data["points"][:5000], default=str)
    polygons_json = json.dumps(geo_data["polygons"][:500], default=str)
    lines_json = json.dumps(geo_data["lines"][:500], default=str)
    bounds_json = json.dumps(geo_data["bounds"]) if geo_data["bounds"] else "null"
    summary = geo_data["summary"]

    # Stats for header
    n_pts = len(geo_data["points"])
    n_poly = len(geo_data["polygons"])
    n_lines = len(geo_data["lines"])

    # Check if points have numeric values for color gradient
    has_values = any(p.get("value") and p["value"] != "" for p in geo_data["points"][:100])

    return f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Map: {title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #000; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; }}
  #header {{
    position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
    background: rgba(0, 0, 0, 0.85); backdrop-filter: blur(8px);
    padding: 10px 20px; display: flex; justify-content: space-between;
    align-items: center; border-bottom: 1px solid #333;
  }}
  #header h2 {{ font-size: 15px; color: #FFD700; font-weight: 600; }}
  #header .stats {{ font-size: 12px; color: #888; }}
  #map {{ position: fixed; top: 42px; bottom: 0; left: 0; right: 0; }}
  .leaflet-container {{ background: #0a0a0a !important; }}

  /* Dark popup styling */
  .leaflet-popup-content-wrapper {{
    background: rgba(20, 20, 30, 0.95) !important;
    color: #e0e0e0 !important; border: 1px solid #FFD700 !important;
    border-radius: 6px !important; font-size: 12px !important;
  }}
  .leaflet-popup-tip {{ background: rgba(20, 20, 30, 0.95) !important; }}
  .popup-table {{ border-collapse: collapse; width: 100%; }}
  .popup-table td {{ padding: 2px 8px; border-bottom: 1px solid #333; }}
  .popup-table td:first-child {{ color: #888; }}
  .popup-table td:last-child {{ color: #FFD700; font-weight: 500; }}

  /* Legend */
  #legend {{
    position: fixed; bottom: 20px; right: 20px; z-index: 1000;
    background: rgba(0,0,0,0.85); padding: 12px 16px;
    border: 1px solid #333; border-radius: 8px; font-size: 12px;
  }}
  .legend-item {{ display: flex; align-items: center; margin: 4px 0; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }}
  .legend-line {{ width: 20px; height: 2px; margin-right: 8px; }}

  /* Scale bar dark override */
  .leaflet-control-scale-line {{
    background: rgba(0,0,0,0.7) !important; color: #aaa !important;
    border-color: #555 !important;
  }}
  .leaflet-control-zoom a {{
    background: #1a1a1a !important; color: #ccc !important;
    border-color: #333 !important;
  }}
  .leaflet-control-zoom a:hover {{ background: #333 !important; }}
</style>
</head>
<body>

<div id="header">
  <h2>📍 {title or 'Step Output'}</h2>
  <div class="stats">{summary} &nbsp;|&nbsp; India Region</div>
</div>

<div id="map"></div>

<div id="legend">
  <div style="color:#aaa; margin-bottom:6px; font-weight:600;">Legend</div>
  {'<div class="legend-item"><div class="legend-dot" style="background:#FFD700"></div>Points ('+str(n_pts)+')</div>' if n_pts else ''}
  {'<div class="legend-item"><div class="legend-dot" style="background:#FFD700;border-radius:2px;width:14px;height:14px;opacity:0.4"></div>Polygons ('+str(n_poly)+')</div>' if n_poly else ''}
  {'<div class="legend-item"><div class="legend-line" style="background:#FFD700"></div>Lines ('+str(n_lines)+')</div>' if n_lines else ''}
</div>

<script>
// ── Data ──
const points = {points_json};
const polygons = {polygons_json};
const lines = {lines_json};
const dataBounds = {bounds_json};

// ── Map Setup ──
var map = L.map('map', {{
    center: {INDIA_CENTER},
    zoom: {INDIA_ZOOM},
    zoomControl: true,
    preferCanvas: true,
}});

// Dark tile layer — CartoDB Dark Matter (black bg, gray boundaries)
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_noannotation/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
}}).addTo(map);

// India boundary overlay (gray)
// Using a simpler approach: CartoDB labels layer for boundaries
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_only_labels/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    subdomains: 'abcd',
    maxZoom: 19,
    opacity: 0.5,
}}).addTo(map);

// ── Color scale for values ──
function valueColor(val, minVal, maxVal) {{
    if (val === null || val === '' || isNaN(val)) return '#FFD700';
    var t = (parseFloat(val) - minVal) / (maxVal - minVal || 1);
    t = Math.max(0, Math.min(1, t));
    // Yellow (#FFD700) to Red (#FF4444) gradient
    var r = 255;
    var g = Math.round(215 - t * 147);
    var b = Math.round(t * 68);
    return 'rgb(' + r + ',' + g + ',' + b + ')';
}}

// ── Plot Points ──
if (points.length > 0) {{
    // Compute value range
    var numVals = points.filter(p => p.value !== '' && !isNaN(p.value)).map(p => parseFloat(p.value));
    var minVal = numVals.length ? Math.min(...numVals) : 0;
    var maxVal = numVals.length ? Math.max(...numVals) : 1;
    var hasNumericValues = numVals.length > points.length * 0.3;

    var ptGroup = L.layerGroup();

    points.forEach(function(p) {{
        var color = '#FFD700';
        if (hasNumericValues && p.value !== '' && !isNaN(p.value)) {{
            color = valueColor(p.value, minVal, maxVal);
        }}

        var radius = points.length > 1000 ? 3 : points.length > 200 ? 4 : 6;

        var marker = L.circleMarker([p.lat, p.lon], {{
            radius: radius,
            fillColor: color,
            color: '#FFD700',
            weight: 1,
            opacity: 0.9,
            fillOpacity: 0.85,
        }});

        // Popup
        var popupHtml = '<table class="popup-table">';
        popupHtml += '<tr><td>Lat</td><td>' + p.lat.toFixed(6) + '</td></tr>';
        popupHtml += '<tr><td>Lon</td><td>' + p.lon.toFixed(6) + '</td></tr>';
        if (p.label) popupHtml += '<tr><td>Label</td><td>' + p.label + '</td></tr>';
        if (p.value !== '') popupHtml += '<tr><td>Value</td><td>' + p.value + '</td></tr>';
        popupHtml += '</table>';
        marker.bindPopup(popupHtml);

        ptGroup.addLayer(marker);
    }});

    ptGroup.addTo(map);
}}

// ── Plot Polygons ──
polygons.forEach(function(poly) {{
    var latlngs = poly.coords.map(c => [c[1], c[0]]);
    var pg = L.polygon(latlngs, {{
        color: '#FFD700',
        weight: 2,
        fillColor: '#FFD700',
        fillOpacity: 0.15,
        dashArray: null,
    }}).addTo(map);

    var popupHtml = '<table class="popup-table">';
    if (poly.label) popupHtml += '<tr><td>Name</td><td>' + poly.label + '</td></tr>';
    var props = poly.properties || {{}};
    Object.keys(props).slice(0, 8).forEach(function(k) {{
        if (k !== 'name' && k !== 'Name')
            popupHtml += '<tr><td>' + k + '</td><td>' + props[k] + '</td></tr>';
    }});
    popupHtml += '</table>';
    pg.bindPopup(popupHtml);
}});

// ── Plot Lines ──
lines.forEach(function(line) {{
    var latlngs = line.coords.map(c => [c[1], c[0]]);
    var pl = L.polyline(latlngs, {{
        color: '#FFD700',
        weight: 3,
        opacity: 0.9,
    }}).addTo(map);

    if (line.label) {{
        pl.bindPopup('<table class="popup-table"><tr><td>Name</td><td>' + line.label + '</td></tr></table>');
    }}
}});

// ── Fit bounds ──
if (dataBounds) {{
    map.fitBounds([
        [dataBounds[1], dataBounds[0]],
        [dataBounds[3], dataBounds[2]]
    ], {{ padding: [40, 40], maxZoom: 16 }});
}} else {{
    map.fitBounds({INDIA_BOUNDS});
}}

// Scale bar
L.control.scale({{ imperial: false, position: 'bottomleft' }}).addTo(map);
</script>
</body>
</html>"""
