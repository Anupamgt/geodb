"""
Agent Store — save, load, list, delete created agents.
Agents are stored as JSON files in the agents/ directory.
"""
import json
import os
from geodb.agent_factory.config import AGENTS_DIR
from geodb.agent_factory.runtime.agent_spec import AgentSpec


def save(spec: AgentSpec) -> str:
    """Save an agent. Returns the agent_id."""
    os.makedirs(AGENTS_DIR, exist_ok=True)
    path = os.path.join(AGENTS_DIR, f"{spec.agent_id}.json")
    spec.save_json(path)
    return spec.agent_id


def load(agent_id: str) -> AgentSpec:
    """Load an agent by ID."""
    path = os.path.join(AGENTS_DIR, f"{agent_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Agent not found: {agent_id}")
    return AgentSpec.load_json(path)


def list_agents() -> list:
    """List all saved agents. Returns list of summary dicts."""
    if not os.path.isdir(AGENTS_DIR):
        return []
    result = []
    for f in sorted(os.listdir(AGENTS_DIR)):
        if f.endswith(".json"):
            try:
                path = os.path.join(AGENTS_DIR, f)
                with open(path) as fh:
                    d = json.load(fh)
                result.append({
                    "id": d.get("agent_id", f[:-5]),
                    "description": d.get("description", ""),
                    "created": d.get("created", ""),
                    "version": d.get("version", 1),
                    "inputs": [i.get("role", "?") for i in d.get("input_spec", [])],
                    "output_format": d.get("output_spec", {}).get("format", "?"),
                    "steps": len(d.get("steps", [])),
                })
            except Exception:
                pass
    return result


def delete(agent_id: str) -> bool:
    """Delete an agent. Returns True if deleted."""
    path = os.path.join(AGENTS_DIR, f"{agent_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def exists(agent_id: str) -> bool:
    path = os.path.join(AGENTS_DIR, f"{agent_id}.json")
    return os.path.exists(path)
