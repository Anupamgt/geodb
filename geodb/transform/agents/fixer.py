"""
Agent 4 — Fixer
Takes: failed code + traceback + step description
Produces: corrected Python code
Only invoked when sandbox execution fails at runtime.
"""
import re
from geodb.transform.config import GEO_LIBRARIES_CONTEXT


SYSTEM = """\
You are a Python debugging expert specializing in geospatial code.
You receive code that failed at runtime along with the full traceback.
Fix the code so it runs correctly.

Output ONLY the complete corrected Python code inside ```python``` fences.
No explanation — just the fixed code.

COMMON FIXES:
- ImportError: use alternative library or correct import path
- NameError: 'X' is not defined: a function was called but never defined in this file.
  Define it inline before the call, or replace the call with its equivalent inline logic.
  Example fix for get_utm_epsg(lon, lat):
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
- IndexError/KeyError: add bounds checking, verify column names
- CRS mismatch: add reprojection step
- NoData handling: mask invalid values before computation
- File format: check reader parameters, encoding
- Geometry errors: validate/fix geometry before operations
- rasterio window/bounds: ensure coordinates are within raster extent
"""


def run(code: str, error: str, step, llm) -> str:
    """
    Fix failed code given the error traceback.

    Args:
        code: the code that failed
        error: stderr / traceback string
        step: Step object for context
        llm: LLMClient

    Returns: fixed Python code string
    """
    # Trim traceback to last 40 lines
    error_lines = error.strip().split("\n")
    if len(error_lines) > 40:
        error_lines = error_lines[-40:]
    trimmed_error = "\n".join(error_lines)

    prompt = f"""{GEO_LIBRARIES_CONTEXT}

STEP: {step.name}
DESCRIPTION: {step.description}
INPUTS: {step.inputs}
EXPECTED OUTPUTS: {step.outputs}

FAILED CODE:
```python
{code}
```

ERROR / TRACEBACK:
```
{trimmed_error}
```

Fix the code. Output the complete corrected code."""

    raw = llm.generate(prompt, system=SYSTEM)
    return _extract_code(raw)


def _extract_code(text: str) -> str:
    m = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()
