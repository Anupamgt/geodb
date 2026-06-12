"""
Step Runner — executes agent steps one by one.
After each step: shows results, waits for user validation.
User can: proceed, retry, view code, show map, abort.
"""
import os
import shutil
import time

from geodb.agent_factory.config import MAX_RUN_RETRIES, OUTPUT_DIR as DEFAULT_OUTPUT
from geodb.agent_factory.runtime.sandbox import Sandbox
from geodb.agent_factory.creation.step_coder import generate_step_code, fix_step_code
from geodb.agent_factory.maps.renderer import render_step_map, open_map


def run_steps_interactive(agent, files: list, llm, params: dict = None,
                          output_dir: str = None, verbose: bool = False) -> dict:
    """
    Execute all agent steps sequentially with user validation.

    Args:
        agent: AgentSpec with .steps populated
        files: list of input file paths
        llm: LLMClient
        params: parameter overrides
        output_dir: where to copy final outputs
        verbose: show extra trace

    Returns: {
        success: bool,
        steps: list of AgentStep (with status updated),
        output_files: dict,
        aborted: bool,
    }
    """
    out_dir = output_dir or DEFAULT_OUTPUT
    os.makedirs(out_dir, exist_ok=True)

    # Merge parameters
    run_params = {}
    for k, v in agent.parameters.items():
        run_params[k] = v.get("default") if isinstance(v, dict) else v
    if params:
        run_params.update(params)

    # Build initial file map: filename → actual path
    file_map = {}
    for fp in files:
        file_map[os.path.basename(fp)] = os.path.abspath(fp)

    completed_steps = []
    all_output_files = {}
    aborted = False

    total = len(agent.steps)

    for step in agent.steps:
        print(f"\n{'━' * 60}")
        print(f"  Step {step.id}/{total}: {step.name}")
        print(f"  {step.description}")
        print(f"  Inputs: {step.inputs}  →  Outputs: {step.outputs}")
        print(f"{'━' * 60}")

        # Generate code for this step
        success = False
        while not success:
            step.status = "running"

            # Generate code
            print(f"  🤖 Generating code…")
            try:
                code = generate_step_code(
                    step, agent.system_prompt, completed_steps, run_params, llm
                )
                step.code = code
                if verbose:
                    lines = code.strip().split("\n")
                    print(f"  📝 {len(lines)} lines generated")
            except Exception as e:
                print(f"  ❌ Code generation failed: {e}")
                choice = _ask("  [R]etry / [A]bort > ")
                if choice == "a":
                    aborted = True
                    break
                continue

            # Execute in sandbox
            print(f"  ⚡ Executing…")
            result = _execute_step(step, file_map, code)

            if result["success"]:
                step.status = "completed"
                step.exec_time = result["elapsed"]
                step.exec_stdout = result["stdout"]
                step.output_summary = result["stdout"].strip()[-300:] if result["stdout"] else ""

                # Show results
                print(f"  ✅ Done in {result['elapsed']:.1f}s")
                if result["stdout"].strip():
                    print(f"  📤 {result['stdout'].strip()[:300]}")
                print(f"  📁 Outputs: {result['output_files']}")

                # Register outputs for next steps
                for fname, fpath in result["output_paths"].items():
                    file_map[fname] = fpath
                    all_output_files[fname] = fpath

                # Also register under planned output names so next step finds them
                # e.g. plan says "polygon_boundary.geojson" but code wrote "coords.geojson"
                actual_outputs = result["output_paths"]
                for planned_name in step.outputs:
                    if planned_name not in file_map:
                        # Match by extension
                        ext = os.path.splitext(planned_name)[1].lower()
                        matches = [
                            fp for fn, fp in actual_outputs.items()
                            if os.path.splitext(fn)[1].lower() == ext
                        ]
                        if len(matches) == 1:
                            file_map[planned_name] = matches[0]

                # Pre-render map (check if spatial data exists)
                map_path = render_step_map(step.name, result["output_paths"], out_dir)
                has_map = bool(map_path)

                # User validation loop
                while True:
                    choice = _step_prompt(step, has_map=has_map)

                    if choice == "n":
                        completed_steps.append(step)
                        success = True
                        break
                    elif choice == "r":
                        step.status = "pending"
                        step.retries += 1
                        break  # break inner, continue outer while
                    elif choice == "v":
                        print(f"\n{'─' * 40} code {'─' * 40}")
                        print(step.code)
                        print(f"{'─' * 85}\n")
                        continue  # ask again
                    elif choice == "m" and has_map:
                        print(f"  🗺️  Opening map…")
                        open_map(map_path)
                        print(f"  📍 Map: {map_path}")
                        continue  # ask again
                    elif choice == "a":
                        aborted = True
                        success = True
                        break

                if choice == "r":
                    continue  # retry outer while

            else:
                step.status = "failed"
                step.error = result["error"]
                print(f"  ❌ Failed: {result['error'][:200]}")
                if result["stderr"]:
                    # Show last few lines of stderr
                    err_lines = result["stderr"].strip().split("\n")[-5:]
                    for el in err_lines:
                        print(f"     {el}")

                # Offer fix
                choice = _ask("  [F]ix (auto-repair) / [R]etry (regenerate) / [A]bort > ")

                if choice == "f":
                    # Try auto-fix
                    for fix_attempt in range(MAX_RUN_RETRIES):
                        print(f"  🔧 Fix attempt {fix_attempt + 1}/{MAX_RUN_RETRIES} — calling LLM…")
                        try:
                            fixed_code = fix_step_code(
                                step, code, result["error"], agent.system_prompt, llm
                            )
                            step.code = fixed_code
                            result = _execute_step(step, file_map, fixed_code)
                            if result["success"]:
                                step.status = "completed"
                                step.exec_time = result["elapsed"]
                                step.exec_stdout = result["stdout"]
                                step.output_summary = result["stdout"].strip()[-300:]
                                print(f"  ✅ Fixed! Done in {result['elapsed']:.1f}s")
                                if result["stdout"].strip():
                                    print(f"  📤 {result['stdout'].strip()[:300]}")
                                print(f"  📁 Outputs: {result['output_files']}")
                                for fname, fpath in result["output_paths"].items():
                                    file_map[fname] = fpath
                                    all_output_files[fname] = fpath
                                # Register under planned names too
                                for planned_name in step.outputs:
                                    if planned_name not in file_map:
                                        ext = os.path.splitext(planned_name)[1].lower()
                                        matches = [
                                            fp for fn, fp in result["output_paths"].items()
                                            if os.path.splitext(fn)[1].lower() == ext
                                        ]
                                        if len(matches) == 1:
                                            file_map[planned_name] = matches[0]
                                completed_steps.append(step)
                                success = True
                                break
                            else:
                                code = fixed_code  # feed error back for next fix
                                print(f"  ❌ Fix attempt {fix_attempt+1} failed")
                        except Exception as e:
                            print(f"  ⚠️  Fix error: {e}")

                    if not success:
                        choice2 = _ask("  Auto-fix exhausted. [R]etry / [A]bort > ")
                        if choice2 == "a":
                            aborted = True
                            success = True  # break out of while

                elif choice == "r":
                    step.retries += 1
                    continue  # regenerate from scratch

                elif choice == "a":
                    aborted = True
                    success = True

        if aborted:
            break

    # Copy final outputs to output_dir
    for fname, fpath in all_output_files.items():
        dst = os.path.join(out_dir, fname)
        if os.path.isfile(fpath) and fpath != dst:
            shutil.copy2(fpath, dst)

    return {
        "success": all(s.status == "completed" for s in agent.steps) and not aborted,
        "steps": agent.steps,
        "output_files": all_output_files,
        "aborted": aborted,
    }


def run_steps_auto(agent, files: list, llm, params: dict = None,
                   output_dir: str = None, verbose: bool = False) -> dict:
    """
    Execute all steps without user interaction (auto mode).
    Same as interactive but skips prompts — proceeds automatically.
    """
    out_dir = output_dir or DEFAULT_OUTPUT
    os.makedirs(out_dir, exist_ok=True)

    run_params = {}
    for k, v in agent.parameters.items():
        run_params[k] = v.get("default") if isinstance(v, dict) else v
    if params:
        run_params.update(params)

    file_map = {}
    for fp in files:
        file_map[os.path.basename(fp)] = os.path.abspath(fp)

    completed_steps = []
    all_output_files = {}

    for step in agent.steps:
        _vlog(verbose, f"\n━━━ Step {step.id}: {step.name} ━━━")

        step.status = "running"
        code = generate_step_code(step, agent.system_prompt, completed_steps, run_params, llm)
        step.code = code

        result = _execute_step(step, file_map, code)

        if not result["success"]:
            # Try fix
            for _ in range(MAX_RUN_RETRIES):
                fixed = fix_step_code(step, code, result["error"], agent.system_prompt, llm)
                result = _execute_step(step, file_map, fixed)
                if result["success"]:
                    code = fixed
                    break

        if result["success"]:
            step.status = "completed"
            step.exec_time = result["elapsed"]
            step.exec_stdout = result["stdout"]
            step.code = code
            for fname, fpath in result["output_paths"].items():
                file_map[fname] = fpath
                all_output_files[fname] = fpath
            # Register under planned names too
            for planned_name in step.outputs:
                if planned_name not in file_map:
                    ext = os.path.splitext(planned_name)[1].lower()
                    matches = [
                        fp for fn, fp in result["output_paths"].items()
                        if os.path.splitext(fn)[1].lower() == ext
                    ]
                    if len(matches) == 1:
                        file_map[planned_name] = matches[0]
            completed_steps.append(step)
            _vlog(verbose, f"  ✅ {result['stdout'].strip()[:150]}" if result["stdout"] else "  ✅ Done")
        else:
            step.status = "failed"
            step.error = result["error"]
            _vlog(verbose, f"  ❌ {result['error'][:150]}")
            break

    for fname, fpath in all_output_files.items():
        dst = os.path.join(out_dir, fname)
        if os.path.isfile(fpath) and fpath != dst:
            shutil.copy2(fpath, dst)

    return {
        "success": all(s.status == "completed" for s in agent.steps),
        "steps": agent.steps,
        "output_files": all_output_files,
        "aborted": False,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _execute_step(step, file_map: dict, code: str) -> dict:
    """Execute one step's code in a sandbox."""
    sandbox = Sandbox()

    # Copy only this step's required inputs
    needed = {}
    for inp in step.inputs:
        if inp in file_map:
            needed[inp] = file_map[inp]
        else:
            # Fallback: match by extension when exact name not found
            ext = os.path.splitext(inp)[1].lower()
            candidates = [
                (fn, fp) for fn, fp in file_map.items()
                if os.path.splitext(fn)[1].lower() == ext and os.path.isfile(fp)
            ]
            if len(candidates) == 1:
                # Copy under the expected name so generated code finds it
                needed[inp] = candidates[0][1]
    # Also copy all available outputs (in case step needs them implicitly)
    for fname, fpath in file_map.items():
        if fname not in needed and os.path.isfile(fpath):
            needed[fname] = fpath

    try:
        sandbox.setup_inputs(needed)
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": "",
                "output_files": [], "output_paths": {},
                "elapsed": 0, "error": f"Input setup: {e}"}

    result = sandbox.execute(code)

    output_paths = sandbox.get_all_output_paths()

    return {
        "success": result["success"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "output_files": list(output_paths.keys()),
        "output_paths": output_paths,
        "elapsed": result["elapsed"],
        "error": result["error"],
    }


def _step_prompt(step, has_map=False):
    """Prompt user after a successful step."""
    while True:
        opts = "[N]ext / [R]etry / [V]iew code"
        if has_map:
            opts += " / [M]ap"
        opts += " / [A]bort"
        choice = input(f"  {opts} > ").strip().lower()
        if choice in ("n", "r", "v", "a"):
            return choice
        if choice == "m" and has_map:
            return choice
        print("  Choose " + ("N, R, V, M, or A" if has_map else "N, R, V, or A"))


def _ask(prompt):
    """Simple input with first-char normalization."""
    while True:
        choice = input(prompt).strip().lower()
        if choice and choice[0] in ("n", "r", "v", "a", "f"):
            return choice[0]
        print("  Invalid choice")


def _vlog(verbose, msg):
    if verbose:
        print(msg)
