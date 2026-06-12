"""
Agent 3 — Verifier
Stage 1: Static AST analysis (import whitelist, blocked patterns, output file check)
Stage 2: LLM semantic review (correctness, edge cases)
"""
import re
from geodb.transform.config import GEO_LIBRARIES_CONTEXT
from geodb.transform.pipeline.sandbox import check_code_safety


SYSTEM = """\
You are a code reviewer for geospatial Python scripts.
You receive: the step description, the generated code, and the expected inputs/outputs.

Check:
1. Code implements the step description correctly
2. Reads from INPUT_DIR, writes to OUTPUT_DIR
3. Produces the declared output files
4. Handles nodata/NaN
5. Handles CRS correctly (reprojects when needed for metric ops)
6. No bugs, no off-by-one errors, correct array indexing
7. Imports are valid

Respond EXACTLY as:
VERDICT: PASS
ISSUES: none

  — or —

VERDICT: FAIL
ISSUES: <list of problems>
FIXED_CODE:
```python
<corrected code>
```
"""


def run(code: str, step, plan_context: dict, llm) -> dict:
    """
    Full verification: static then LLM.
    Returns { passed: bool, issues: list, fixed_code: str|None }
    """
    # Stage 1: static
    s = _static_check(code, step)
    if not s["passed"]:
        return s

    # Stage 2: LLM
    v = _llm_check(code, step, plan_context, llm)

    # Merge
    if s["issues"]:
        v["issues"] = s["issues"] + v["issues"]
    return v


def _static_check(code: str, step) -> dict:
    """Instant safety and structure checks."""
    result = {"passed": True, "issues": [], "fixed_code": None}

    # Safety scan
    violations = check_code_safety(code)
    if violations:
        return {"passed": False, "issues": violations, "fixed_code": None}

    # Check code references OUTPUT_DIR
    if "OUTPUT_DIR" not in code and "output_path" not in code.lower():
        result["issues"].append("Warning: code may not write to OUTPUT_DIR")

    # Check expected output filenames are referenced in code
    for out_file in step.outputs:
        if out_file not in code:
            result["issues"].append(f"Warning: expected output '{out_file}' not found in code")

    return result


def _llm_check(code: str, step, plan_context: dict, llm) -> dict:
    """LLM semantic verification."""
    prompt = f"""{GEO_LIBRARIES_CONTEXT}

STEP: {step.name}
DESCRIPTION: {step.description}
INPUTS: {step.inputs}
EXPECTED OUTPUTS: {step.outputs}

CODE:
```python
{code}
```

Review this code. Respond with VERDICT, ISSUES, and (if FAIL) FIXED_CODE."""

    raw = llm.generate(prompt, system=SYSTEM, temperature=0.05)
    return _parse_response(raw)


def _parse_response(text: str) -> dict:
    result = {"passed": False, "issues": [], "fixed_code": None}

    m = re.search(r'VERDICT:\s*(PASS|FAIL)', text, re.IGNORECASE)
    if m:
        result["passed"] = m.group(1).upper() == "PASS"

    m = re.search(r'ISSUES:\s*(.*?)(?:FIXED_CODE:|$)', text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        if raw.lower() not in ("none", "n/a", ""):
            result["issues"] = [
                l.strip().lstrip("-•* ")
                for l in raw.split("\n")
                if l.strip() and l.strip().lower() not in ("none", "n/a")
            ]

    if not result["passed"]:
        m = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if m:
            fixed = m.group(1).strip()
            if fixed:
                result["fixed_code"] = fixed

    return result
