"""
Prompt Builder — assembles the specialist system prompt for a created agent
from knowledge base patterns + example I/O analysis.
"""


def build_system_prompt(task: str, input_infos: list, output_analysis: dict,
                        io_mapping: dict, knowledge: dict, output_info: dict) -> str:
    """
    Build a detailed specialist system prompt.

    Args:
        task: user's task description
        input_infos: inspected input files
        output_analysis: analyzed output structure
        io_mapping: input→output mapping
        knowledge: {key: content} from knowledge loader
        output_info: inspected output file

    Returns: the full system prompt string
    """
    sections = []

    # Section 1: Role
    sections.append(f"""\
You are a specialist geospatial processing agent.
Your task: {task}

You will receive input files and must produce output in a specific format.
Write complete Python code that performs this task.""")

    # Section 2: Input/Output contract
    sections.append("\n--- INPUT FILES ---")
    for inp in input_infos:
        desc = f"- {inp['name']} ({inp.get('file_format', inp['type'])})"
        if inp.get("feature_count"):
            desc += f", {inp['feature_count']} features, types: {inp.get('geometry_types', {})}"
        if inp.get("bands"):
            desc += f", {inp['bands']} band(s), {inp.get('dtype','')}, resolution: {inp.get('resolution')}"
        if inp.get("data_class"):
            desc += f", class: {inp['data_class']}"
        if inp.get("bounds"):
            desc += f", bounds: {inp['bounds']}"
        sections.append(desc)

    # Output contract
    struct = output_analysis.get("structure", {})
    sections.append("\n--- EXPECTED OUTPUT ---")
    fmt = output_info.get("file_format", output_info.get("type", ""))
    sections.append(f"Format: {fmt}")

    if struct.get("type") == "tabular":
        sections.append(f"Rows: variable (depends on input geometry)")
        sections.append(f"Columns (MUST match exactly):")
        for col in struct.get("columns", []):
            desc = f"  - {col['name']}: {col.get('role', '?')}"
            if col.get("is_numeric"):
                desc += f" (numeric)"
            if col.get("pattern"):
                desc += f" [{col['pattern']}]"
            if col.get("monotonic"):
                desc += " [monotonically increasing]"
            sections.append(desc)

        params = struct.get("derived_params", {})
        if params:
            sections.append(f"\nDerived parameters: {params}")

    elif struct.get("type") == "geojson":
        sections.append(f"Features: {struct.get('feature_count', '?')}")
        sections.append(f"Geometry: {struct.get('geometry_types', {})}")
        sections.append(f"Properties: {struct.get('properties', [])}")

    elif struct.get("type") == "raster":
        sections.append(f"Bands: {struct.get('bands')}, dtype: {struct.get('dtype')}")

    # Section 3: Transformation description
    sections.append(f"\n--- TRANSFORMATION ---")
    sections.append(f"Type: {io_mapping.get('transformation_type', 'unknown')}")
    sections.append(f"Operations: {io_mapping.get('operations', [])}")
    sections.append(f"Column sources:")
    for col, source in io_mapping.get("column_sources", {}).items():
        sections.append(f"  - {col} ← {source}")
    if io_mapping.get("requires_crs_transform"):
        sections.append("CRS: Project to UTM for metric operations, back to WGS84 for output")

    # Section 4: Code patterns from knowledge base
    if knowledge:
        # Separate pre-built patterns from fallback/auto-generated
        prebuilt = {k: v for k, v in knowledge.items()
                    if k not in ("fallback_hints", "auto_generated")}
        auto = knowledge.get("auto_generated", "")
        fallback = knowledge.get("fallback_hints", "")

        if prebuilt:
            sections.append("\n--- CODE PATTERNS (use these) ---")
            for key, content in prebuilt.items():
                sections.append(f"\n## {key}")
                sections.append(content)

        if auto:
            sections.append("\n--- CODE PATTERNS (auto-generated reference) ---")
            sections.append(auto)

        if fallback and not prebuilt and not auto:
            sections.append(f"\n{fallback}")

    # Section 5: Code conventions
    sections.append("""\
\n--- CODE CONVENTIONS ---
- INPUT_DIR and OUTPUT_DIR are pre-defined variables (do NOT redefine them)
- Read inputs from: os.path.join(INPUT_DIR, 'filename')
- Write outputs to: os.path.join(OUTPUT_DIR, 'filename')
- Handle KMZ by unzipping first to get KML
- Handle nodata values (skip or mark as None/NaN)
- Handle CRS: reproject if needed for metric calculations
- Import everything you need at the top
- Print a summary at the end (row count, value ranges, etc.)
- Output ONLY the Python code inside ```python``` fences""")

    return "\n".join(sections)
