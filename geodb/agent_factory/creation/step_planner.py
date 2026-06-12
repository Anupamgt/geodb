"""
Step Planner — breaks a task into ordered sub-steps.
Each step is atomic, has clear inputs/outputs, and chains into the next.
"""
import json
import os
import re
from geodb.agent_factory.runtime.agent_spec import AgentStep


SYSTEM = """\
You are a geospatial pipeline planner. Break the task into 2-6 small sequential steps.
Each step does ONE thing. Steps chain: step 2 reads step 1's output.

RULES:
- Use the ACTUAL uploaded filenames in step 1 inputs.
- KMZ files must be unzipped first as a SEPARATE step. The KML inside is always named "doc.kml".
  So step 1 inputs=["file.kmz"], outputs=["doc.kml"].
- Intermediate files: .geojson for vectors, .csv for tabular, .tif for rasters.
- Each step's outputs MUST match the NEXT step's inputs EXACTLY (same filenames).
- The LAST step MUST always be "write_output" that writes the FINAL output file.
  The last step takes the processed data and writes it to the DESIRED OUTPUT filename.
- Each step must list its exact input and output filenames.
- DEM/TIF files are passed through as-is. Use the ORIGINAL tif filename in any step that needs it.

Output ONLY JSON inside ```json``` fences:
{
  "steps": [
    {
      "id": 1,
      "name": "unzip_kmz",
      "description": "Unzip the KMZ to extract doc.kml",
      "inputs": ["actual_file.kmz"],
      "outputs": ["doc.kml"]
    },
    {
      "id": 2,
      "name": "parse_kml",
      "description": "Parse doc.kml to extract polygon geometry as GeoJSON",
      "inputs": ["doc.kml"],
      "outputs": ["geometry.geojson"]
    },
    {
      "id": 3,
      "name": "process_data",
      "description": "Process the data (sampling, measurements, etc.)",
      "inputs": ["geometry.geojson", "DEM_demo.tif"],
      "outputs": ["processed.geojson"]
    },
    {
      "id": 4,
      "name": "write_output",
      "description": "Convert processed data to final CSV output",
      "inputs": ["processed.geojson"],
      "outputs": ["result.csv"]
    }
  ]
}
"""


def plan_steps(task: str, input_infos: list, output_spec: dict,
               parameters: dict, llm) -> list:
    """
    Break a task into ordered sub-steps.

    Args:
        task: what the agent does
        input_infos: inspected input file dicts
        output_spec: {format, filename_pattern, description}
        parameters: agent parameters
        llm: LLMClient

    Returns: list of AgentStep
    """
    file_descs = []
    for info in input_infos:
        desc = f"- {info['name']} ({info.get('file_format', info['type'])})"
        if info.get("feature_count"):
            desc += f", {info['feature_count']} features"
        if info.get("bands"):
            desc += f", {info['bands']} bands, {info.get('dtype','')}"
        if info.get("data_class"):
            desc += f", class: {info['data_class']}"
        if info.get("bounds"):
            desc += f", bounds: {info['bounds']}"
        file_descs.append(desc)

    out_fmt = output_spec.get("format", "csv")
    out_name = output_spec.get("filename_pattern", f"output.{out_fmt}")

    prompt = f"""TASK: {task}

INPUT FILES:
{chr(10).join(file_descs)}

DESIRED OUTPUT: {out_name} ({out_fmt})
  {output_spec.get('description', '')}

PARAMETERS: {json.dumps(parameters, default=str)}

Break this into sequential steps. Each step does ONE thing."""

    raw = llm.generate(prompt, system=SYSTEM)
    steps_data = _extract_json(raw)

    steps = []
    for s in steps_data.get("steps", []):
        steps.append(AgentStep(
            id=s["id"],
            name=s.get("name", f"step_{s['id']}"),
            description=s.get("description", ""),
            inputs=s.get("inputs", []),
            outputs=s.get("outputs", []),
            needs=s.get("needs", [i for i in range(1, s["id"])]),
        ))

    # Ensure at least one step
    if not steps:
        steps = [AgentStep(
            id=1, name="process",
            description=task,
            inputs=[i["name"] for i in input_infos],
            outputs=[out_name],
        )]

    # Enforce: last step must output the final file
    last = steps[-1]
    if out_name not in last.outputs:
        # Check if any step already outputs it
        has_final = any(out_name in s.outputs for s in steps)
        if not has_final:
            # Add a write_output step
            last_outputs = last.outputs if last.outputs else [f"processed.{out_fmt}"]
            steps.append(AgentStep(
                id=last.id + 1,
                name="write_output",
                description=f"Write the final output as {out_name}",
                inputs=last_outputs,
                outputs=[out_name],
            ))

    # Enforce: filename consistency between steps
    for i in range(1, len(steps)):
        prev_outputs = steps[i - 1].outputs
        curr_inputs = steps[i].inputs
        # If current step expects a file that previous step outputs under a different name
        # but same extension, align them
        for j, cinp in enumerate(curr_inputs):
            if cinp not in prev_outputs:
                ext = os.path.splitext(cinp)[1].lower()
                matches = [o for o in prev_outputs if os.path.splitext(o)[1].lower() == ext]
                if len(matches) == 1:
                    # Rename current input to match previous output
                    steps[i].inputs[j] = matches[0]

    return steps


def _extract_json(text):
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"steps": []}
