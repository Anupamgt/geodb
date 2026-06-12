"""
Agent Runner — execute an AgentSpec on actual files.
Mode A: use code_template (fast, no LLM)
Mode B: use system_prompt + LLM (flexible, handles edge cases)
Falls back from A to B if template execution fails.
"""
import os
import re
import shutil
from geodb.agent_factory.config import MAX_RUN_RETRIES
from geodb.agent_factory.runtime.sandbox import Sandbox
from geodb.agent_factory.runtime.validator import validate
from geodb.agent_factory.runtime import agent_spec as spec_mod
from geodb.agent_factory.analysis.file_inspector import inspect


def run_agent(agent: spec_mod.AgentSpec, files: list, params: dict = None,
              llm=None, output_dir: str = None, verbose: bool = False) -> dict:
    """
    Execute an agent on the given files.

    Args:
        agent: AgentSpec to run
        files: list of file paths
        params: parameter overrides
        llm: LLMClient (needed for Mode B)
        output_dir: where to copy final outputs
        verbose: print trace

    Returns: { success, output_files, validation, stdout, stderr, error, mode }
    """
    # Merge parameters
    run_params = {}
    for k, v in agent.parameters.items():
        run_params[k] = v.get("default") if isinstance(v, dict) else v
    if params:
        run_params.update(params)

    # Map files to input roles
    file_map = _map_files_to_inputs(agent, files)
    _log(verbose, f"📁 File mapping: {file_map}")

    errors = []   # collect errors from each mode for diagnostics

    # Mode A: Try code template first
    if agent.code_template:
        _log(verbose, "⚡ Mode A: executing code template…")
        result = _execute_template(agent, file_map, run_params, verbose)
        if result["success"]:
            # Validate
            val = validate(result["output_dir"], agent.validation_rules)
            result["validation"] = val
            if val["passed"]:
                _log(verbose, "✅ Template execution + validation passed")
                if output_dir:
                    _copy_outputs(result["output_dir"], output_dir)
                result["mode"] = "template"
                return result
            else:
                _log(verbose, f"⚠️  Template output failed validation: "
                             f"{[r['detail'] for r in val['results'] if not r['passed']]}")
        else:
            err = result.get("error", "") or result.get("stderr", "")
            errors.append(f"Mode A: {err}")
            _log(verbose, f"   ⚠️  Template error: {err[:300]}")

    # Mode B: LLM generation
    if llm:
        _log(verbose, "🤖 Mode B: LLM code generation…")
        result = _execute_llm(agent, file_map, run_params, llm, verbose)
        if result["success"]:
            val = validate(result["output_dir"], agent.validation_rules)
            result["validation"] = val
            if output_dir:
                _copy_outputs(result["output_dir"], output_dir)
            result["mode"] = "llm"
            return result

        # Retry with error context
        for attempt in range(1, MAX_RUN_RETRIES + 1):
            _log(verbose, f"🔧 Fixing (attempt {attempt})…")
            result = _execute_llm_fix(agent, file_map, run_params,
                                      result.get("code", ""), result.get("error", ""),
                                      llm, verbose)
            if result["success"]:
                val = validate(result["output_dir"], agent.validation_rules)
                result["validation"] = val
                if output_dir:
                    _copy_outputs(result["output_dir"], output_dir)
                result["mode"] = "llm_fixed"
                return result

    combined_error = "All execution modes failed"
    if errors:
        combined_error += ":\n" + "\n".join(errors)

    return {
        "success": False,
        "output_files": {},
        "validation": {"passed": False, "results": []},
        "stdout": "", "stderr": "",
        "error": combined_error,
        "mode": "failed",
        "output_dir": "",
    }


def _map_files_to_inputs(agent, files):
    """Map uploaded file paths to agent's expected input roles."""
    file_map = {}
    file_infos = [(f, os.path.splitext(f)[1].lower().lstrip(".")) for f in files]

    for inp_spec in agent.input_spec:
        expected_types = inp_spec.get("type", [])
        if isinstance(expected_types, str):
            expected_types = [expected_types]

        for fpath, fext in file_infos:
            if fext in expected_types and fpath not in file_map.values():
                file_map[os.path.basename(fpath)] = fpath
                break

    # Also add all files by their actual names
    for fpath, _ in file_infos:
        fname = os.path.basename(fpath)
        if fname not in file_map:
            file_map[fname] = fpath

    return file_map


def _execute_template(agent, file_map, params, verbose):
    """Execute the code template with parameter substitution."""
    code = agent.code_template

    # Substitute parameters
    for k, v in params.items():
        code = code.replace(f"{{{k}}}", str(v))

    # Substitute file placeholders
    for fname in file_map:
        code = code.replace("{polygon_file}", fname)
        code = code.replace("{dem_file}", fname)
        code = code.replace("{input_file}", fname)
        ext = os.path.splitext(fname)[1].lower()
        if ext in (".kml", ".kmz", ".geojson"):
            code = code.replace("{polygon_file}", fname)
            code = code.replace("{vector_file}", fname)
        elif ext in (".tif", ".tiff"):
            code = code.replace("{raster_file}", fname)
            code = code.replace("{dem_file}", fname)

    sandbox = Sandbox()
    sandbox.setup_inputs(file_map)
    result = sandbox.execute(code)

    return {
        "success": result["success"],
        "output_files": sandbox.get_all_output_paths(),
        "output_dir": sandbox.output_dir,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "error": result["error"],
        "code": code,
        "sandbox": sandbox,
    }


def _execute_llm(agent, file_map, params, llm, verbose):
    """Generate and execute code using the agent's system prompt."""
    filenames = list(file_map.keys())

    prompt = f"""Input files available in INPUT_DIR: {filenames}
Parameters: {params}

Write the complete Python code to perform this task.
Remember INPUT_DIR and OUTPUT_DIR are already defined.
Use the EXACT filenames listed above."""

    raw = llm.generate(prompt, system=agent.system_prompt)
    code = _extract_code(raw)
    _log(verbose, f"📝 Generated {len(code.split(chr(10)))} lines")

    sandbox = Sandbox()
    sandbox.setup_inputs(file_map)
    result = sandbox.execute(code)

    return {
        "success": result["success"],
        "output_files": sandbox.get_all_output_paths(),
        "output_dir": sandbox.output_dir,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "error": result["error"],
        "code": code,
        "sandbox": sandbox,
    }


def _execute_llm_fix(agent, file_map, params, failed_code, error, llm, verbose):
    """Fix failed code using the agent's system prompt + error context."""
    prompt = f"""The previous code FAILED with this error:
```
{error[-1000:]}
```

Previous code:
```python
{failed_code}
```

Fix the code. Input files: {list(file_map.keys())}
Parameters: {params}
OUTPUT the complete corrected Python code."""

    raw = llm.generate(prompt, system=agent.system_prompt)
    code = _extract_code(raw)

    sandbox = Sandbox()
    sandbox.setup_inputs(file_map)
    result = sandbox.execute(code)

    return {
        "success": result["success"],
        "output_files": sandbox.get_all_output_paths(),
        "output_dir": sandbox.output_dir,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "error": result["error"],
        "code": code,
        "sandbox": sandbox,
    }


def _extract_code(text):
    m = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def _copy_outputs(src_dir, dst_dir):
    """Copy all output files to the final destination."""
    os.makedirs(dst_dir, exist_ok=True)
    for f in os.listdir(src_dir):
        src = os.path.join(src_dir, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dst_dir, f))


def _log(verbose, msg):
    if verbose:
        print(f"  {msg}")
