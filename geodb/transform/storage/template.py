"""
Pipeline template storage — save, load, list, delete reusable pipelines.
Templates are stored as JSON files in the pipelines/ directory.
"""
import json
import os
from datetime import datetime
from geodb.transform.config import PIPELINES_DIR
from geodb.transform.pipeline.step import StepPlan, Step


def save(plan: StepPlan, steps: list, template_id: str = None) -> str:
    """
    Save a completed pipeline as a reusable template.

    Args:
        plan: the original StepPlan
        steps: list of Step objects with code populated
        template_id: custom name (default: auto from task)

    Returns: template_id
    """
    os.makedirs(PIPELINES_DIR, exist_ok=True)

    if not template_id:
        # Generate from task
        template_id = plan.task.lower()
        template_id = "".join(c if c.isalnum() or c == " " else "" for c in template_id)
        template_id = "_".join(template_id.split()[:5])

    doc = {
        "template_id": template_id,
        "version": 1,
        "created": datetime.now().isoformat(),
        "task": plan.task,
        "required_inputs": plan.input_files,
        "output": plan.output,
        "parameters": plan.parameters,
        "steps": [],
    }

    for step in steps:
        doc["steps"].append({
            "id": step.id,
            "name": step.name,
            "description": step.description,
            "inputs": step.inputs,
            "outputs": step.outputs,
            "needs": step.needs,
            "viz_hint": step.viz_hint,
            "code": step.code,
            "verified": step.verified,
        })

    path = os.path.join(PIPELINES_DIR, f"{template_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, default=str)

    return template_id


def load(template_id: str) -> dict:
    """Load a template by ID. Returns raw dict."""
    path = os.path.join(PIPELINES_DIR, f"{template_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Template not found: {template_id}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_as_plan(template_id: str) -> tuple:
    """Load a template and return (StepPlan, list[Step])."""
    doc = load(template_id)
    plan = StepPlan(
        task=doc["task"],
        input_files=doc.get("required_inputs", []),
        output=doc.get("output", {}),
        parameters=doc.get("parameters", {}),
    )
    steps = []
    for s in doc.get("steps", []):
        step = Step.from_dict(s)
        step.code = s.get("code", "")
        step.verified = s.get("verified", False)
        steps.append(step)
    plan.steps = steps
    return plan, steps


def list_templates() -> list:
    """List all saved templates. Returns list of summary dicts."""
    if not os.path.isdir(PIPELINES_DIR):
        return []
    result = []
    for f in sorted(os.listdir(PIPELINES_DIR)):
        if f.endswith(".json"):
            try:
                path = os.path.join(PIPELINES_DIR, f)
                with open(path) as fh:
                    doc = json.load(fh)
                result.append({
                    "id": doc.get("template_id", f[:-5]),
                    "task": doc.get("task", ""),
                    "created": doc.get("created", ""),
                    "steps": len(doc.get("steps", [])),
                    "inputs": [i.get("type", "?") for i in doc.get("required_inputs", [])],
                })
            except Exception:
                pass
    return result


def delete(template_id: str) -> bool:
    """Delete a template. Returns True if deleted."""
    path = os.path.join(PIPELINES_DIR, f"{template_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
