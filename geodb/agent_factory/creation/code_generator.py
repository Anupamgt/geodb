"""
Code Generator — generates a working code template for the agent.
The template has {placeholder}s for filenames and parameters.
"""
import ast
import re


SYSTEM = """\
You are a geospatial Python expert. Generate COMPLETE working Python code
for the described task.

CRITICAL:
- The code must be COMPLETE and RUNNABLE — not pseudocode.
- INPUT_DIR and OUTPUT_DIR are ALREADY defined — do NOT redefine them.
- Use os.path.join(INPUT_DIR, 'filename') to read inputs.
- Use os.path.join(OUTPUT_DIR, 'filename') to write outputs.
- Handle all edge cases: nodata, CRS mismatches, empty geometries.
- Print a summary at the end.
- Output ONLY Python code inside ```python``` fences.
"""


def generate(agent_system_prompt: str, input_filenames: list,
             output_filename: str, params: dict, llm) -> str:
    """
    Generate a working code template.

    Args:
        agent_system_prompt: the specialist prompt with all patterns
        input_filenames: actual input file names
        output_filename: expected output filename
        params: parameter dict (name → value)
        llm: LLMClient

    Returns: Python code string
    """
    prompt = f"""{agent_system_prompt}

INPUT FILES in INPUT_DIR: {input_filenames}
OUTPUT FILE to write in OUTPUT_DIR: {output_filename}
PARAMETERS: {params}

Generate the complete Python code. INPUT_DIR and OUTPUT_DIR are already defined."""

    raw = llm.generate(prompt, system=SYSTEM, max_tokens=6000)
    code = _extract_code(raw)

    # Clean up: remove any re-definition of INPUT_DIR/OUTPUT_DIR
    code = _clean_code(code)

    # Fix missing imports
    code = _fix_missing_imports(code)

    return code


def templatize(code: str, filenames: list, params: dict) -> str:
    """
    Convert concrete code to a template by replacing specific filenames
    and parameter values with {placeholders}.
    """
    template = code

    # Replace parameter values with placeholders
    for key, val in params.items():
        if isinstance(val, (int, float)):
            # Replace the numeric literal
            template = template.replace(str(val), f"{{{key}}}")

    # Don't templatize filenames aggressively — keep them as-is
    # The runner will handle filename mapping
    return template


def _extract_code(text):
    m = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try to find code that starts with import
    lines = text.strip().split("\n")
    code_lines = []
    started = False
    for line in lines:
        if line.strip().startswith(("import ", "from ", "#")):
            started = True
        if started:
            code_lines.append(line)
    return "\n".join(code_lines) if code_lines else text.strip()


def _clean_code(code):
    """Remove problematic patterns from generated code."""
    lines = code.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip re-definitions of INPUT_DIR/OUTPUT_DIR
        if stripped.startswith("INPUT_DIR") and "=" in stripped and "os.environ" not in stripped:
            if "os.path.join" not in stripped:
                continue
        if stripped.startswith("OUTPUT_DIR") and "=" in stripped and "os.environ" not in stripped:
            if "os.path.join" not in stripped:
                continue
        cleaned.append(line)
    return "\n".join(cleaned)


# ── Import validation ────────────────────────────────────────────────

# Top-level modules that can be detected as bare names in code and
# safely added as `import <module>`.  Only stdlib + known geo stack.
_AUTO_IMPORTABLE = {
    "zipfile", "tempfile", "shutil", "hashlib",
    "json", "csv", "math", "re", "glob", "sys", "os",
    "datetime", "time", "copy", "warnings", "io", "struct",
    "collections", "itertools", "functools", "pathlib",
    "numpy", "pandas", "geopandas", "fiona", "pyproj",
    "rasterio", "shapely", "openpyxl", "xlsxwriter",
    "matplotlib", "scipy", "lxml",
    "PIL",
}

# Common aliases: if the code uses `np.` it needs `import numpy as np`
_ALIAS_MAP = {
    "np":  "import numpy as np",
    "pd":  "import pandas as pd",
    "plt": "import matplotlib.pyplot as plt",
    "gpd": "import geopandas as gpd",
}


def _get_existing_imports(code: str) -> set[str]:
    """Return the set of top-level module names already imported."""
    imported = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Fall back to regex if code doesn't parse
        for m in re.finditer(
            r'^\s*(?:import|from)\s+([\w.]+)', code, re.MULTILINE
        ):
            imported.add(m.group(1).split(".")[0])
        return imported

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
                if alias.asname:
                    imported.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    return imported


def _find_used_modules(code: str) -> set[str]:
    """Detect top-level module names and aliases used as identifiers."""
    used = set()
    # Match `module.something` patterns (e.g. zipfile.ZipFile, tempfile.mkdtemp)
    for m in re.finditer(r'\b(\w+)\.\w+', code):
        name = m.group(1)
        if name in _AUTO_IMPORTABLE or name in _ALIAS_MAP:
            used.add(name)
    return used


def _fix_missing_imports(code: str) -> str:
    """Detect modules used but not imported and inject the missing imports."""
    existing = _get_existing_imports(code)
    used = _find_used_modules(code)

    missing_lines = []
    for name in sorted(used - existing):
        if name in _ALIAS_MAP:
            missing_lines.append(_ALIAS_MAP[name])
        elif name in _AUTO_IMPORTABLE:
            missing_lines.append(f"import {name}")

    if not missing_lines:
        return code

    # Insert after the last existing import line
    lines = code.split("\n")
    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            last_import_idx = i

    if last_import_idx >= 0:
        for j, imp in enumerate(missing_lines):
            lines.insert(last_import_idx + 1 + j, imp)
    else:
        # No imports at all — prepend
        lines = missing_lines + [""] + lines

    return "\n".join(lines)
