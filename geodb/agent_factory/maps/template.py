"""
Fixed map template — dark theme, India region, gray boundaries, yellow overlay.
No LLM needed. Just inject GeoJSON data and render.
"""

# India state boundaries GeoJSON URL (Natural Earth via CDN)
INDIA_BOUNDARY_URL = "https://raw.githubusercontent.com/geohacker/india/master/state/india_state.geojson"


def build_map_html(geojson_features: list, bounds: list = None,
                   title: str = "Step Output", summary: str = "") -> str:
    """
    Build a self-contained HTML map with:
    - Dark CartoDB tiles
    - Gray India state boundaries
    - Yellow data overlay (points, lines, polygons)
    - Click popups with properties
    - Fit to data bounds or default India view

    Args:
        geojson_features: list of GeoJSON Feature dicts
        bounds: [minlon, minlat, maxlon, maxlat] or None (defaults to India)
        title: map title
        summary: stats summary text

    Returns: complete HTML string
    """
    import json

    data_json = json.dumps(geojson_features, default=str)

    # Default India center and zoom
    center_lat = 22.5
    center_lon = 78.5
    default_zoom = 5

    # If we have bounds, we'll fitBounds in JS
    bounds_js = "null"
    if bounds:
        bounds_js = f"[[{bounds[1]}, {bounds[0]}], [{bounds[3]}, {bounds[2]}]]"

    return f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: #0a0a0a;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Consolas', monospace;
}}
#header {{
    background: #111;
    padding: 12px 20px;
    border-bottom: 2px solid #333;
    display: flex;
    justify-content: space-between;
    align-items: center;
}}
#header h1 {{
    font-size: 16px;
    color: #FFD700;
    font-weight: 600;
}}
#header .stats {{
    font-size: 13px;
    color: #888;
}}
#map {{
    width: 100%;
    height: calc(100vh - 50px);
}}
.leaflet-popup-content-wrapper {{
    background: #1a1a1a;
    color: #e0e0e0;
    border: 1px solid #444;
    border-radius: 6px;
    font-size: 12px;
}}
.leaflet-popup-tip {{
    background: #1a1a1a;
    border: 1px solid #444;
}}
.leaflet-popup-content {{
    margin: 8px 12px;
}}
.leaflet-popup-content table {{
    border-collapse: collapse;
}}
.leaflet-popup-content td {{
    padding: 2px 8px 2px 0;
    border-bottom: 1px solid #333;
    font-size: 11px;
}}
.leaflet-popup-content td:first-child {{
    color: #888;
    font-weight: bold;
}}
.info-panel {{
    position: absolute;
    bottom: 20px;
    left: 20px;
    z-index: 1000;
    background: rgba(17, 17, 17, 0.9);
    padding: 10px 16px;
    border-radius: 6px;
    border: 1px solid #333;
    font-size: 12px;
    color: #aaa;
    max-width: 300px;
}}
.info-panel .count {{
    color: #FFD700;
    font-weight: bold;
}}
.legend {{
    position: absolute;
    top: 60px;
    right: 20px;
    z-index: 1000;
    background: rgba(17, 17, 17, 0.9);
    padding: 10px 14px;
    border-radius: 6px;
    border: 1px solid #333;
    font-size: 12px;
}}
.legend-item {{
    display: flex;
    align-items: center;
    margin: 4px 0;
}}
.legend-dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 8px;
    border: 1px solid #555;
}}
</style>
</head>
<body>

<div id="header">
    <h1>{title}</h1>
    <div class="stats">{summary}</div>
</div>
<div id="map"></div>

<div class="info-panel">
    <span class="count" id="featureCount">0</span> features loaded<br/>
    <span id="coordDisplay">Hover map for coordinates</span>
</div>

<div class="legend">
    <div class="legend-item">
        <div class="legend-dot" style="background:#FFD700;"></div>
        <span>Data overlay</span>
    </div>
    <div class="legend-item">
        <div class="legend-dot" style="background:transparent;border-color:#555;"></div>
        <span>State boundaries</span>
    </div>
</div>

<script>
// ── Data ──────────────────────────────────────────────
const DATA = {data_json};
const DATA_BOUNDS = {bounds_js};

// ── Map Setup ─────────────────────────────────────────
var map = L.map('map', {{
    center: [{center_lat}, {center_lon}],
    zoom: {default_zoom},
    zoomControl: true,
    attributionControl: false,
}});

// Dark tiles
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_nolabels/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    maxZoom: 19,
    subdomains: 'abcd',
}}).addTo(map);

// Labels on top (separate layer so they render above data)
var labelsPane = map.createPane('labels');
labelsPane.style.zIndex = 650;
labelsPane.style.pointerEvents = 'none';
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_only_labels/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    maxZoom: 19,
    subdomains: 'abcd',
    pane: 'labels',
}}).addTo(map);

// ── India Boundaries (gray) ───────────────────────────
fetch('{INDIA_BOUNDARY_URL}')
    .then(r => r.json())
    .then(data => {{
        L.geoJSON(data, {{
            style: {{
                color: '#444',
                weight: 1,
                fillColor: 'transparent',
                fillOpacity: 0,
            }},
            interactive: false,
        }}).addTo(map);
    }})
    .catch(() => {{
        // Boundaries failed to load — continue without them
        console.log('India boundaries not loaded');
    }});

// ── Data Overlay (yellow) ─────────────────────────────
var dataLayer = L.geoJSON({{
    type: 'FeatureCollection',
    features: DATA
}}, {{
    // Points → yellow circle markers
    pointToLayer: function(feature, latlng) {{
        return L.circleMarker(latlng, {{
            radius: 5,
            fillColor: '#FFD700',
            color: '#FFD700',
            weight: 1,
            opacity: 0.9,
            fillOpacity: 0.7,
        }});
    }},
    // Lines and polygons → yellow stroke
    style: function(feature) {{
        var gt = feature.geometry.type;
        if (gt === 'Polygon' || gt === 'MultiPolygon') {{
            return {{
                color: '#FFD700',
                weight: 2,
                fillColor: '#FFD700',
                fillOpacity: 0.15,
            }};
        }}
        return {{
            color: '#FFD700',
            weight: 3,
            opacity: 0.9,
        }};
    }},
    // Click popup with properties
    onEachFeature: function(feature, layer) {{
        if (feature.properties && Object.keys(feature.properties).length > 0) {{
            var html = '<table>';
            for (var key in feature.properties) {{
                var val = feature.properties[key];
                if (val !== null && val !== '' && val !== undefined) {{
                    // Truncate long values
                    var display = String(val);
                    if (display.length > 50) display = display.substring(0, 47) + '...';
                    // Round numbers
                    if (!isNaN(val) && val !== '') {{
                        var num = parseFloat(val);
                        if (num !== Math.floor(num)) display = num.toFixed(4);
                    }}
                    html += '<tr><td>' + key + '</td><td>' + display + '</td></tr>';
                }}
            }}
            html += '</table>';
            layer.bindPopup(html);
        }}
    }}
}}).addTo(map);

// ── Fit Bounds ────────────────────────────────────────
if (DATA_BOUNDS) {{
    map.fitBounds(DATA_BOUNDS, {{ padding: [40, 40], maxZoom: 16 }});
}} else if (DATA.length > 0) {{
    try {{
        map.fitBounds(dataLayer.getBounds(), {{ padding: [40, 40], maxZoom: 16 }});
    }} catch(e) {{}}
}}

// ── Feature Count ─────────────────────────────────────
document.getElementById('featureCount').textContent = DATA.length;

// ── Mouse Coordinates ─────────────────────────────────
map.on('mousemove', function(e) {{
    document.getElementById('coordDisplay').textContent =
        'Lat: ' + e.latlng.lat.toFixed(5) + '  Lon: ' + e.latlng.lng.toFixed(5);
}});

</script>
</body>
</html>"""
