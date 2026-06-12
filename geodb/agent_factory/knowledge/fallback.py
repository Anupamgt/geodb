"""
Fallback Knowledge (Option C) — provides generic guidance when no
pre-built knowledge patterns exist for a file format or transformation.

This is a zero-cost fallback: no extra LLM call, just a structured hint
block injected into Section 4 of the prompt.
"""

# Maps file extensions to likely Python libraries
FORMAT_LIBRARY_HINTS = {
    # Vector formats
    ".kml":      {"lib": "lxml.etree", "note": "Parse XML with namespace {http://www.opengis.net/kml/2.2}"},
    ".kmz":      {"lib": "zipfile + lxml.etree", "note": "Unzip KMZ to get doc.kml, then parse as KML"},
    ".geojson":  {"lib": "json or geopandas", "note": "json.load() for lightweight, geopandas.read_file() for spatial ops"},
    ".shp":      {"lib": "geopandas or fiona", "note": "geopandas.read_file() reads all components (.shx, .dbf, .prj)"},
    ".gpx":      {"lib": "gpxpy or lxml.etree", "note": "gpxpy.parse() for tracks/waypoints/routes"},
    ".gml":      {"lib": "geopandas or lxml.etree", "note": "geopandas.read_file() with driver='GML'"},
    ".gpkg":     {"lib": "geopandas or fiona", "note": "geopandas.read_file() — single file, multiple layers"},
    ".dxf":      {"lib": "geopandas or ezdxf", "note": "geopandas.read_file() or ezdxf for CAD features"},
    ".osm":      {"lib": "osmium or lxml.etree", "note": "osmium for large files, lxml for small extracts"},
    ".topojson": {"lib": "topojson or json", "note": "topojson.Topology() or parse as JSON manually"},
    # Raster formats
    ".tif":      {"lib": "rasterio", "note": "rasterio.open() for reading bands, transform, CRS"},
    ".tiff":     {"lib": "rasterio", "note": "Same as .tif"},
    ".img":      {"lib": "rasterio", "note": "ERDAS Imagine format — rasterio.open() works"},
    ".nc":       {"lib": "xarray or netCDF4", "note": "xarray.open_dataset() for multidimensional data"},
    ".hdf":      {"lib": "h5py or rasterio", "note": "h5py for raw access, rasterio for georeferenced"},
    ".asc":      {"lib": "rasterio or numpy", "note": "ASCII grid — rasterio.open() or np.loadtxt with header parsing"},
    ".dem":      {"lib": "rasterio", "note": "Treat as single-band raster"},
    # Tabular / output formats
    ".csv":      {"lib": "pandas or csv", "note": "pandas.read_csv() / pandas.to_csv()"},
    ".xlsx":     {"lib": "openpyxl or pandas", "note": "pandas.read_excel() / pandas.to_excel()"},
    ".json":     {"lib": "json", "note": "json.load() / json.dump()"},
    ".parquet":  {"lib": "pandas or geopandas", "note": "pandas.read_parquet() — fast columnar format"},
}

# Maps transformation types to generic strategies
TRANSFORM_STRATEGIES = {
    "coordinate_extraction": "Parse input geometry, iterate all coordinates, write lon/lat/alt to output.",
    "format_conversion":     "Read input with appropriate library, convert geometry/attributes, write to output format.",
    "profile_extraction":    "Extract line geometry, sample DEM at regular intervals along line, output distance vs elevation.",
    "grid_sampling":         "Generate grid of points within polygon, sample raster at each point.",
    "point_sampling":        "Extract point coordinates, sample raster value at each point.",
    "geometry_measurement":  "Calculate area/perimeter/length. Reproject to UTM for metric units.",
    "raster_clip":           "Use polygon as mask to clip raster. Write clipped raster to output.",
    "raster_processing":     "Read raster bands, apply transformation, write result.",
    "contour_extraction":    "Generate contour lines from raster at specified intervals.",
    "vector_processing":     "Read vector data, apply spatial operations, write result.",
    "visualization":         "Read data, create matplotlib/folium visualization, save as image/html.",
    "tabular_extraction":    "Extract attributes/properties from spatial features into table format.",
}


def build_fallback_knowledge(input_infos: list, output_format: str,
                             transformation_type: str = "") -> str:
    """
    Build a generic knowledge section when no pre-built patterns exist.

    Args:
        input_infos: inspected input file dicts
        output_format: output file extension (e.g. "csv", "geojson")
        transformation_type: inferred transformation type

    Returns:
        A string to inject as Section 4 of the prompt, or "" if nothing useful.
    """
    sections = []

    sections.append("--- LIBRARY GUIDANCE (no pre-built patterns available) ---")
    sections.append(
        "No specific code patterns are pre-loaded for this combination.\n"
        "Use the library hints below and your Python knowledge to write correct code.\n"
    )

    # Input format hints
    seen_exts = set()
    for info in input_infos:
        ext = "." + info.get("file_format", info.get("type", "")).lower()
        if ext in FORMAT_LIBRARY_HINTS and ext not in seen_exts:
            seen_exts.add(ext)
            hint = FORMAT_LIBRARY_HINTS[ext]
            sections.append(f"Input format `{ext}`:")
            sections.append(f"  Library: {hint['lib']}")
            sections.append(f"  Note: {hint['note']}")

    # Output format hint
    out_ext = "." + output_format.lower().lstrip(".")
    if out_ext in FORMAT_LIBRARY_HINTS:
        hint = FORMAT_LIBRARY_HINTS[out_ext]
        sections.append(f"\nOutput format `{out_ext}`:")
        sections.append(f"  Library: {hint['lib']}")
        sections.append(f"  Note: {hint['note']}")

    # Transformation strategy
    if transformation_type and transformation_type in TRANSFORM_STRATEGIES:
        sections.append(f"\nStrategy for '{transformation_type}':")
        sections.append(f"  {TRANSFORM_STRATEGIES[transformation_type]}")

    # General safety hints
    sections.append("""
General patterns:
- Always open files using os.path.join(INPUT_DIR, filename) or os.path.join(OUTPUT_DIR, filename)
- For XML/KML parsing, use open(path, 'rb') as file object instead of passing path string to etree.parse()
- For coordinate extraction, handle both 2D (lon,lat) and 3D (lon,lat,alt) formats
- For CRS operations, detect input CRS and reproject to UTM for metric calculations
- Handle empty geometries, missing attributes, and nodata values gracefully
- Print a summary at the end: row count, coordinate count, value ranges""")

    return "\n".join(sections)
