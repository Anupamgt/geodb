"""
Agent Creator — builds specialist AgentSpec with multi-step plan.
Two modes: with examples (precise) or without (inferred).
"""
import os
import re
import json
from datetime import datetime

from geodb.agent_factory.runtime.agent_spec import AgentSpec, AgentStep
from geodb.agent_factory.analysis import file_inspector, output_analyzer, io_mapper
from geodb.agent_factory.knowledge.loader import load_for_task, load_one, load_or_generate
from geodb.agent_factory.creation import prompt_builder, validator_builder
from geodb.agent_factory.creation.step_planner import plan_steps


def create_agent(task, example_inputs=None, example_output=None,
                 files=None, llm=None, agent_id=None, verbose=False):
    """
    Create a specialist agent with a multi-step plan.
    Provide (example_inputs + example_output) for precise mode, or just files for inferred mode.
    """
    if example_inputs and example_output:
        return _create_with_examples(task, example_inputs, example_output, llm, agent_id, verbose)
    elif files:
        return _create_without_examples(task, files, llm, agent_id, verbose)
    else:
        raise ValueError("Provide either (example_inputs + example_output) or files")


# ── Mode 1: With Examples ─────────────────────────────────────────────────────

def _create_with_examples(task, example_inputs, example_output, llm, agent_id, verbose):
    _log(verbose, "🔍 Phase 1: Analyzing example files…")

    input_infos = [file_inspector.inspect(f) for f in example_inputs]
    output_info = file_inspector.inspect(example_output)

    _log(verbose, f"   Inputs: {[i['name']+'('+i.get('file_format',i['type'])+')' for i in input_infos]}")
    _log(verbose, f"   Output: {output_info['name']} ({output_info.get('file_format',output_info['type'])})")

    output_anal = output_analyzer.analyze_output(output_info)
    struct = output_anal.get("structure", {})
    if struct.get("type") == "tabular":
        cols = struct.get("columns", [])
        _log(verbose, f"   Columns: {[c['name']+'('+c.get('role','?')+')' for c in cols]}")

    mapping = io_mapper.map_io(input_infos, output_anal)
    _log(verbose, f"   Transform: {mapping['transformation_type']}")

    out_fmt = os.path.splitext(example_output)[1].lstrip(".")
    knowledge = load_or_generate(
        transformation_type=mapping["transformation_type"],
        input_infos=input_infos,
        output_format=out_fmt,
        task_description=task,
        verbose=verbose,
    )
    _log(verbose, f"   Knowledge: {list(knowledge.keys())}")

    system_prompt = prompt_builder.build_system_prompt(
        task, input_infos, output_anal, mapping, knowledge, output_info
    )

    out_name = os.path.basename(example_output)
    derived = struct.get("derived_params", {}) if struct.get("type") == "tabular" else {}
    agent_params = {k: {"default": v, "type": type(v).__name__, "description": "from example"}
                    for k, v in derived.items() if k != "pattern"}

    output_spec = {
        "format": output_info.get("type", ""),
        "filename_pattern": out_name,
        "description": task,
    }
    if struct.get("type") == "tabular" and struct.get("columns"):
        output_spec["columns"] = [{"name": c["name"], "role": c.get("role","")}
                                   for c in struct["columns"]]

    val_rules = validator_builder.build_rules(output_info, output_anal)

    # Generate multi-step plan
    _log(verbose, "\n📋 Phase 2: Planning steps…")
    steps = plan_steps(task, input_infos, output_spec, agent_params, llm)
    for s in steps:
        _log(verbose, f"   Step {s.id}: {s.name} — {s.description[:60]}")
        _log(verbose, f"     in: {s.inputs} → out: {s.outputs}")

    if not agent_id:
        agent_id = _make_id(task)

    spec = AgentSpec(
        agent_id=agent_id, description=task, version=1,
        created=datetime.now().isoformat(),
        input_spec=_build_input_spec(input_infos),
        output_spec=output_spec, parameters=agent_params,
        system_prompt=system_prompt, validation_rules=val_rules,
        example_reference={"input_files": [i["name"] for i in input_infos],
                           "output_file": output_info["name"]},
        knowledge_used=list(knowledge.keys()),
        allowed_libs=_default_libs(),
        steps=steps,
    )

    return spec


# ── Mode 2: Without Examples ──────────────────────────────────────────────────

INFER_SYSTEM = """\
You are a geospatial pipeline architect. Given a task and input files, determine:
1. Output format and structure
2. Output filename
3. Transformation type

Output ONLY JSON inside ```json``` fences:
{
  "output_format": "csv|xlsx|geojson|tif|shp|kml|html|png",
  "output_filename": "result.csv",
  "output_description": "what the output contains",
  "output_columns": ["col1", "col2"],
  "transformation_type": "profile_extraction|grid_sampling|point_sampling|geometry_measurement|coordinate_extraction|raster_clip|raster_processing|contour_extraction|vector_processing|visualization|format_conversion",
  "parameters": {}
}
"""


def _create_without_examples(task, files, llm, agent_id, verbose):
    _log(verbose, "🔍 Phase 1: Inspecting input files…")

    input_infos = [file_inspector.inspect(f) for f in files]
    for info in input_infos:
        _log(verbose, f"   {info['name']} ({info.get('file_format',info['type'])})")
        if info.get("feature_count"):
            _log(verbose, f"     features={info['feature_count']}")
        if info.get("data_class"):
            _log(verbose, f"     class={info['data_class']}")

    _log(verbose, "\n🤖 Inferring output structure…")
    inferred = _infer_output(task, input_infos, llm)
    _log(verbose, f"   Format: {inferred.get('output_format')}, File: {inferred.get('output_filename')}")
    _log(verbose, f"   Transform: {inferred.get('transformation_type')}")

    transform_type = inferred.get("transformation_type", "tabular_extraction")
    out_fmt = inferred.get("output_format", "csv")

    # Smart knowledge loading: pre-built → cloud auto-gen → fallback
    knowledge = load_or_generate(
        transformation_type=transform_type,
        input_infos=input_infos,
        output_format=out_fmt,
        task_description=task,
        verbose=verbose,
    )

    # Always ensure format-specific basics are loaded if available
    for info in input_infos:
        if info.get("file_format") in ("kml", "kmz") and "kml_parsing" not in knowledge:
            k = load_one("kml_parsing")
            if k: knowledge["kml_parsing"] = k
        if info.get("file_format") == "geotiff" and "rasterio" not in knowledge:
            k = load_one("rasterio")
            if k: knowledge["rasterio"] = k
    _log(verbose, f"   Knowledge: {list(knowledge.keys())}")

    system_prompt = _build_prompt_no_examples(task, input_infos, inferred, knowledge)

    out_fmt = inferred.get("output_format", "csv")
    out_name = inferred.get("output_filename", f"output.{out_fmt}")
    output_spec = {
        "format": out_fmt, "filename_pattern": out_name,
        "description": inferred.get("output_description", task),
    }
    if inferred.get("output_columns"):
        output_spec["columns"] = [{"name": c, "role": ""} for c in inferred["output_columns"]]

    agent_params = {k: {"default": v, "type": type(v).__name__, "description": "inferred"}
                    for k, v in inferred.get("parameters", {}).items()}

    out_ext = os.path.splitext(out_name)[1]
    val_rules = [
        {"check": "file_exists", "pattern": f"*{out_ext}"},
        {"check": "file_min_size", "file": f"*{out_ext}", "min_bytes": 50},
    ]

    # Generate multi-step plan
    _log(verbose, "\n📋 Planning steps…")
    steps = plan_steps(task, input_infos, output_spec, agent_params, llm)
    for s in steps:
        _log(verbose, f"   Step {s.id}: {s.name} — {s.description[:60]}")

    if not agent_id:
        agent_id = _make_id(task)

    spec = AgentSpec(
        agent_id=agent_id, description=task, version=1,
        created=datetime.now().isoformat(),
        input_spec=_build_input_spec(input_infos),
        output_spec=output_spec, parameters=agent_params,
        system_prompt=system_prompt, validation_rules=val_rules,
        example_reference={},
        knowledge_used=list(knowledge.keys()),
        allowed_libs=_default_libs(),
        steps=steps,
    )

    return spec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _infer_output(task, input_infos, llm):
    file_descs = []
    for info in input_infos:
        desc = f"- {info['name']} ({info.get('file_format', info['type'])})"
        if info.get("feature_count"): desc += f", {info['feature_count']} features"
        if info.get("bands"): desc += f", {info['bands']} bands"
        if info.get("data_class"): desc += f", class: {info['data_class']}"
        if info.get("bounds"): desc += f", bounds: {info['bounds']}"
        file_descs.append(desc)

    prompt = f"TASK: {task}\n\nINPUT FILES:\n{chr(10).join(file_descs)}\n\nDetermine output format and transformation."
    raw = llm.generate(prompt, system=INFER_SYSTEM)

    m = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try: return json.loads(m.group())
        except json.JSONDecodeError: pass
    return {"output_format": "csv", "output_filename": "output.csv",
            "transformation_type": "tabular_extraction"}


def _build_prompt_no_examples(task, input_infos, inferred, knowledge):
    sections = [f"You are a specialist geospatial processing agent.\nYour task: {task}\n"]
    sections.append("--- INPUT FILES ---")
    for inp in input_infos:
        desc = f"- {inp['name']} ({inp.get('file_format', inp['type'])})"
        if inp.get("feature_count"): desc += f", {inp['feature_count']} features"
        if inp.get("bands"): desc += f", {inp['bands']} bands, {inp.get('dtype','')}"
        if inp.get("data_class"): desc += f", class: {inp['data_class']}"
        if inp.get("bounds"): desc += f", bounds: {inp['bounds']}"
        sections.append(desc)
    sections.append(f"\n--- OUTPUT ---\nFormat: {inferred.get('output_format','csv')}")
    sections.append(f"File: {inferred.get('output_filename','output.csv')}")
    if inferred.get("output_columns"):
        sections.append(f"Columns: {inferred['output_columns']}")
    if knowledge:
        prebuilt = {k: v for k, v in knowledge.items()
                    if k not in ("fallback_hints", "auto_generated")}
        auto = knowledge.get("auto_generated", "")
        fallback = knowledge.get("fallback_hints", "")

        if prebuilt:
            sections.append("\n--- CODE PATTERNS ---")
            for key, content in prebuilt.items():
                sections.append(f"\n## {key}\n{content}")
        if auto:
            sections.append("\n--- CODE PATTERNS (auto-generated reference) ---")
            sections.append(auto)
        if fallback and not prebuilt and not auto:
            sections.append(f"\n{fallback}")
    sections.append("\n--- CONVENTIONS ---\n- INPUT_DIR and OUTPUT_DIR are pre-defined (do NOT redefine)\n- Read: os.path.join(INPUT_DIR, 'file')\n- Write: os.path.join(OUTPUT_DIR, 'file')\n- Handle KMZ, nodata, CRS\n- Print summary at end")
    return "\n".join(sections)


def _build_input_spec(input_infos):
    spec = []
    for inp in input_infos:
        itype = inp["type"]
        if itype == "kmz": itype = ["kml", "kmz"]
        elif itype in ("tif", "tiff"): itype = ["tif", "tiff"]
        else: itype = [itype]
        role = "unknown"
        if inp.get("data_class") == "elevation/DEM": role = "dem"
        elif inp.get("file_format") in ("kml", "kmz"): role = "vector"
        elif inp.get("file_format") == "geotiff": role = "raster"
        spec.append({"type": itype, "role": role, "required": True})
    return spec


def _default_libs():
    return list(set(l.split(".")[0] for l in [
        "os","json","numpy","pandas","rasterio","shapely",
        "geopandas","pyproj","openpyxl","lxml","zipfile",
        "math","csv","pathlib","warnings","matplotlib"]))


def _make_id(task):
    words = task.lower().split()[:5]
    return "_".join(w for w in words if w.isalnum())


def _log(verbose, msg):
    if verbose:
        print(f"  {msg}")
