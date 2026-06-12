"""
AgentSpec — complete agent definition.
AgentStep — one sub-step within an agent.
"""
from dataclasses import dataclass, field
import json


@dataclass
class AgentStep:
    """One sub-step in a multi-step agent."""
    id: int
    name: str
    description: str
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    needs: list = field(default_factory=list)

    code: str = ""
    status: str = "pending"
    exec_time: float = 0.0
    exec_stdout: str = ""
    exec_stderr: str = ""
    error: str = ""
    retries: int = 0
    output_summary: str = ""

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description,
                "inputs": self.inputs, "outputs": self.outputs, "needs": self.needs,
                "code": self.code, "status": self.status}

    @classmethod
    def from_dict(cls, d):
        s = cls(id=d["id"], name=d.get("name",""), description=d.get("description",""),
                inputs=d.get("inputs",[]), outputs=d.get("outputs",[]), needs=d.get("needs",[]))
        s.code = d.get("code", "")
        s.status = d.get("status", "pending")
        return s


@dataclass
class AgentSpec:
    agent_id: str
    description: str
    version: int = 1
    created: str = ""
    input_spec: list = field(default_factory=list)
    output_spec: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    system_prompt: str = ""
    code_template: str = ""
    validation_rules: list = field(default_factory=list)
    example_reference: dict = field(default_factory=dict)
    knowledge_used: list = field(default_factory=list)
    allowed_libs: list = field(default_factory=list)
    steps: list = field(default_factory=list)   # list[AgentStep]

    def to_dict(self):
        return {
            "agent_id": self.agent_id, "description": self.description,
            "version": self.version, "created": self.created,
            "input_spec": self.input_spec, "output_spec": self.output_spec,
            "parameters": self.parameters, "system_prompt": self.system_prompt,
            "code_template": self.code_template, "validation_rules": self.validation_rules,
            "example_reference": self.example_reference,
            "knowledge_used": self.knowledge_used, "allowed_libs": self.allowed_libs,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d):
        spec = cls(
            agent_id=d.get("agent_id",""), description=d.get("description",""),
            version=d.get("version",1), created=d.get("created",""),
            input_spec=d.get("input_spec",[]), output_spec=d.get("output_spec",{}),
            parameters=d.get("parameters",{}), system_prompt=d.get("system_prompt",""),
            code_template=d.get("code_template",""), validation_rules=d.get("validation_rules",[]),
            example_reference=d.get("example_reference",{}),
            knowledge_used=d.get("knowledge_used",[]), allowed_libs=d.get("allowed_libs",[]),
        )
        spec.steps = [AgentStep.from_dict(s) for s in d.get("steps",[])]
        return spec

    def save_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)

    @classmethod
    def load_json(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
