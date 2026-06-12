"""
Step — a single unit of work in a transformation pipeline.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Step:
    id: int
    name: str
    description: str
    inputs: list = field(default_factory=list)     # filenames expected
    outputs: list = field(default_factory=list)     # filenames produced
    needs: list = field(default_factory=list)       # step IDs that must finish first
    viz_hint: str = ""                              # suggestion for visualizer

    # Set during execution
    code: str = ""
    status: str = "pending"    # pending | running | completed | failed | skipped
    verified: bool = False
    exec_time: float = 0.0
    exec_stdout: str = ""
    exec_stderr: str = ""
    error: str = ""
    retries: int = 0

    # Viz
    viz_html_path: str = ""
    viz_summary: str = ""

    # Output metadata (auto-extracted after execution)
    output_metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "needs": self.needs,
            "viz_hint": self.viz_hint,
            "code": self.code,
            "status": self.status,
            "verified": self.verified,
            "exec_time": self.exec_time,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            inputs=d.get("inputs", []),
            outputs=d.get("outputs", []),
            needs=d.get("needs", []),
            viz_hint=d.get("viz_hint", ""),
            code=d.get("code", ""),
            status=d.get("status", "pending"),
            verified=d.get("verified", False),
        )


@dataclass
class StepPlan:
    """Full plan produced by the planner agent."""
    task: str
    input_files: list = field(default_factory=list)   # [{name, type, role}]
    output: dict = field(default_factory=dict)         # {format, description}
    parameters: dict = field(default_factory=dict)     # user-tunable params
    steps: list = field(default_factory=list)          # list of Step

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "input_files": self.input_files,
            "output": self.output,
            "parameters": self.parameters,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StepPlan":
        plan = cls(
            task=d["task"],
            input_files=d.get("input_files", []),
            output=d.get("output", {}),
            parameters=d.get("parameters", {}),
        )
        plan.steps = [Step.from_dict(s) for s in d.get("steps", [])]
        return plan
