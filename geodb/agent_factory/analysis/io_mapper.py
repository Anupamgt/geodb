"""
IO Mapper — determines how input files relate to output columns/features.
"""


def map_io(input_infos: list, output_analysis: dict) -> dict:
    """
    Determine the relationship between inputs and output structure.
    Returns a mapping dict describing the transformation.
    """
    struct = output_analysis.get("structure", {})
    mapping = {
        "transformation_type": "unknown",
        "column_sources": {},
        "operations": [],
        "requires_crs_transform": False,
    }

    # Identify input types
    has_polygon = any(
        "Polygon" in str(i.get("geometry_types", {})) for i in input_infos
    )
    has_line = any(
        "LineString" in str(i.get("geometry_types", {})) for i in input_infos
    )
    has_point = any(
        "Point" in str(i.get("geometry_types", {})) for i in input_infos
    )
    has_raster = any(
        i.get("file_format") in ("geotiff",) or i.get("type") in ("tif", "tiff")
        for i in input_infos
    )
    has_dem = any(
        i.get("data_class") == "elevation/DEM" for i in input_infos
    )

    # Determine output type
    if struct.get("type") == "tabular":
        cols = struct.get("columns", [])
        roles = {c.get("role") for c in cols}
        params = struct.get("derived_params", {})

        # Profile/cross-section
        if "distance" in roles and "elevation" in roles:
            if params.get("pattern") == "profile_line":
                mapping["transformation_type"] = "profile_extraction"
                mapping["operations"] = [
                    "parse_geometry", "find_axis_or_line",
                    "generate_sample_points", "sample_raster", "export_table"
                ]
            else:
                mapping["transformation_type"] = "elevation_sampling_along_line"
                mapping["operations"] = [
                    "parse_geometry", "generate_points_along",
                    "sample_raster", "export_table"
                ]

        # Grid sampling
        elif "latitude" in roles and "longitude" in roles and "elevation" in roles:
            if params.get("pattern") == "grid":
                mapping["transformation_type"] = "grid_sampling"
                mapping["operations"] = [
                    "parse_polygon", "generate_grid",
                    "sample_raster", "export_table"
                ]
            else:
                mapping["transformation_type"] = "point_sampling"
                mapping["operations"] = [
                    "parse_geometry", "extract_or_generate_points",
                    "sample_raster", "export_table"
                ]

        # Area/perimeter calculation
        elif "area" in roles or "perimeter" in roles:
            mapping["transformation_type"] = "geometry_measurement"
            mapping["operations"] = [
                "parse_geometry", "project_to_utm",
                "compute_metrics", "export_table"
            ]

        # Coordinate extraction
        elif "latitude" in roles and "longitude" in roles and "elevation" not in roles:
            mapping["transformation_type"] = "coordinate_extraction"
            mapping["operations"] = [
                "parse_geometry", "extract_coordinates", "export_table"
            ]

        # Generic tabular
        else:
            mapping["transformation_type"] = "tabular_extraction"
            mapping["operations"] = [
                "parse_inputs", "process", "export_table"
            ]

        # Map columns to sources
        for col in cols:
            role = col.get("role", "")
            if role in ("latitude", "longitude"):
                mapping["column_sources"][col["name"]] = "derived_from_geometry"
            elif role == "elevation":
                mapping["column_sources"][col["name"]] = "sampled_from_raster"
            elif role == "distance":
                mapping["column_sources"][col["name"]] = "computed_along_geometry"
            elif role == "identifier":
                mapping["column_sources"][col["name"]] = "auto_generated_index"
            elif role in ("area", "perimeter"):
                mapping["column_sources"][col["name"]] = "computed_from_geometry"
            elif role in ("slope", "aspect"):
                mapping["column_sources"][col["name"]] = "derived_from_raster"
            else:
                mapping["column_sources"][col["name"]] = "unknown"

    elif struct.get("type") == "raster":
        if has_dem and has_polygon:
            mapping["transformation_type"] = "raster_clip"
            mapping["operations"] = ["parse_polygon", "clip_raster", "write_raster"]
        elif has_dem:
            mapping["transformation_type"] = "raster_processing"
            mapping["operations"] = ["read_raster", "process", "write_raster"]

    elif struct.get("type") == "geojson":
        if has_dem:
            mapping["transformation_type"] = "contour_extraction"
            mapping["operations"] = ["read_raster", "extract_contours", "write_vector"]
        else:
            mapping["transformation_type"] = "vector_processing"
            mapping["operations"] = ["parse_input", "process", "write_vector"]

    # Check if CRS transform needed
    crses = set()
    for i in input_infos:
        if i.get("crs"):
            crses.add(str(i.get("crs")))
        if i.get("crs_epsg"):
            crses.add(str(i.get("crs_epsg")))
    if len(crses) > 1 or any("UTM" in str(c) for c in crses):
        mapping["requires_crs_transform"] = True
    # Metric operations always need UTM projection
    if mapping["transformation_type"] in (
        "profile_extraction", "grid_sampling", "geometry_measurement",
        "elevation_sampling_along_line"
    ):
        mapping["requires_crs_transform"] = True

    return mapping
