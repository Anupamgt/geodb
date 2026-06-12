"""
Web-aware pipeline runner.
Uses queues instead of input() so the FastAPI layer can drive decisions.
"""
import os
import queue
import shutil
import threading
from dataclasses import dataclass, field
from typing import Optional

from geodb.agent_factory.config import MAX_RUN_RETRIES, OUTPUT_DIR as DEFAULT_OUTPUT
from geodb.agent_factory.runtime.sandbox import Sandbox
from geodb.agent_factory.creation.step_coder import generate_step_code, fix_step_code


# ── Session ───────────────────────────────────────────────────────────────────

@dataclass
class PipelineSession:
    session_id: str
    event_queue: queue.Queue = field(default_factory=queue.Queue)
    decision_queue: queue.Queue = field(default_factory=queue.Queue)
    status: str = "created"   # created|planning|running|awaiting|done|error
    agent: Optional[object] = None
    thread: Optional[threading.Thread] = None
    output_dir: str = ""
    current_step: int = 0
    total_steps: int = 0


def _emit(session: PipelineSession, event_type: str, **data):
    session.event_queue.put({"type": event_type, **data})


def _wait(session: PipelineSession, timeout: int = 600) -> str:
    try:
        return session.decision_queue.get(timeout=timeout)
    except queue.Empty:
        return "abort"


# ── Create + run ──────────────────────────────────────────────────────────────

def run_pipeline_create(session: PipelineSession, task: str, file_paths: list,
                        llm, output_dir: str = None):
    from geodb.agent_factory.creation.agent_creator import create_agent
    from geodb.agent_factory.storage import agent_store
    from geodb.agent_factory.analysis.file_inspector import inspect as inspect_file

    out_dir = output_dir or DEFAULT_OUTPUT
    os.makedirs(out_dir, exist_ok=True)
    session.output_dir = out_dir

    try:
        session.status = "planning"
        _emit(session, "phase", message="Inspecting files and creating agent plan…")

        file_infos = []
        for fp in file_paths:
            try:
                info = inspect_file(fp)
                info["path"] = os.path.abspath(fp)
                file_infos.append(info)
            except Exception as e:
                _emit(session, "log", message=f"Warning: could not inspect {fp}: {e}")

        spec = create_agent(task, files=file_infos, llm=llm)
        session.agent = spec
        session.total_steps = len(spec.steps)

        # Emit plan — wait for approve / regenerate / abort
        _emit(session, "plan",
              agent_id=spec.agent_id,
              description=spec.description,
              steps=[{"id": s.id, "name": s.name, "description": s.description,
                      "inputs": s.inputs, "outputs": s.outputs}
                     for s in spec.steps])

        while True:
            decision = _wait(session)
            if decision == "abort":
                session.status = "done"
                _emit(session, "aborted")
                return
            elif decision == "regenerate":
                _emit(session, "phase", message="Regenerating plan…")
                spec = create_agent(task, files=file_infos, llm=llm)
                session.agent = spec
                session.total_steps = len(spec.steps)
                _emit(session, "plan",
                      agent_id=spec.agent_id,
                      description=spec.description,
                      steps=[{"id": s.id, "name": s.name, "description": s.description,
                              "inputs": s.inputs, "outputs": s.outputs}
                             for s in spec.steps])
            elif decision == "approve":
                break

        agent_store.save(spec)
        _run_steps(session, spec, file_paths, llm, out_dir)

    except Exception as e:
        session.status = "error"
        _emit(session, "error", message=str(e))


def run_pipeline_saved(session: PipelineSession, agent_id: str, file_paths: list,
                       llm, output_dir: str = None, params: dict = None):
    from geodb.agent_factory.storage import agent_store

    out_dir = output_dir or DEFAULT_OUTPUT
    os.makedirs(out_dir, exist_ok=True)
    session.output_dir = out_dir

    try:
        spec = agent_store.load(agent_id)
        if params:
            spec.parameters.update(params)
        session.agent = spec
        session.total_steps = len(spec.steps)
        session.status = "running"
        _emit(session, "phase", message=f"Running agent: {spec.description}")
        _run_steps(session, spec, file_paths, llm, out_dir)
    except Exception as e:
        session.status = "error"
        _emit(session, "error", message=str(e))


# ── Core step loop ────────────────────────────────────────────────────────────

def _run_steps(session: PipelineSession, spec, file_paths: list, llm, out_dir: str):
    run_params = {k: (v.get("default") if isinstance(v, dict) else v)
                  for k, v in spec.parameters.items()}

    file_map = {os.path.basename(fp): os.path.abspath(fp) for fp in file_paths}

    completed = []
    all_outputs = {}
    step_idx = 0

    while step_idx < len(spec.steps):
        step = spec.steps[step_idx]
        session.current_step = step.id
        session.status = "running"

        _emit(session, "step_start",
              step_id=step.id, step_name=step.name,
              description=step.description,
              inputs=step.inputs, outputs=step.outputs,
              total=session.total_steps)

        # Generate code
        _emit(session, "log", message=f"Step {step.id}: generating code…")
        try:
            code = generate_step_code(step, spec.system_prompt, completed, run_params, llm)
            step.code = code
        except Exception as e:
            session.status = "awaiting"
            _emit(session, "step_failed", step_id=step.id, error=str(e), stderr="")
            _emit(session, "step_await", step_id=step.id, options=["retry", "abort"], error=str(e))
            d = _wait(session)
            if d == "abort":
                break
            continue  # retry = regenerate

        # Execute
        _emit(session, "log", message=f"Step {step.id}: executing…")
        result = _run_sandbox(step, file_map, code)

        if result["success"]:
            step.status = "completed"
            step.exec_time = result["elapsed"]
            step.exec_stdout = result["stdout"]
            _register_outputs(step, result["output_paths"], file_map, all_outputs)

            map_path = _try_render_map(step.name, result["output_paths"], out_dir)

            _emit(session, "step_success",
                  step_id=step.id, step_name=step.name,
                  elapsed=round(result["elapsed"], 1),
                  stdout=result["stdout"].strip()[:400],
                  output_files=list(result["output_paths"].keys()),
                  map_path=map_path,
                  code=step.code)

            session.status = "awaiting"
            _emit(session, "step_await", step_id=step.id,
                  options=["next", "retry", "abort"], has_map=bool(map_path))

            d = _wait(session)
            if d == "abort":
                break
            elif d == "retry":
                step.status = "pending"
                step.retries += 1
                continue  # regenerate without incrementing
            else:  # next
                completed.append(step)
                step_idx += 1

        else:
            step.status = "failed"
            step.error = result["error"]
            err_lines = (result["stderr"] or "").strip().split("\n")
            _emit(session, "step_failed",
                  step_id=step.id,
                  error=result["error"][:400],
                  stderr="\n".join(err_lines[-6:]))

            session.status = "awaiting"
            _emit(session, "step_await", step_id=step.id,
                  options=["fix", "retry", "abort"],
                  error=result["error"][:400])

            d = _wait(session)
            if d == "abort":
                break
            elif d == "retry":
                step.retries += 1
                continue
            elif d == "fix":
                fixed = _auto_fix(session, step, code, result["error"],
                                  spec.system_prompt, llm, file_map, all_outputs, out_dir)
                if fixed:
                    completed.append(step)
                    step_idx += 1
                # else: user chose abort/retry from within _auto_fix → handled there
                if session.status in ("done", "error"):
                    return

    # Copy outputs to out_dir
    for fname, fpath in all_outputs.items():
        dst = os.path.join(out_dir, fname)
        if os.path.isfile(fpath) and fpath != dst:
            try:
                shutil.copy2(fpath, dst)
            except Exception:
                pass

    session.status = "done"
    done_files = [f for f in os.listdir(out_dir)
                  if os.path.isfile(os.path.join(out_dir, f))]
    _emit(session, "done",
          output_dir=out_dir,
          output_files=done_files,
          completed=len(completed),
          total=len(spec.steps))


def _auto_fix(session, step, code, error, system_prompt, llm,
              file_map, all_outputs, out_dir) -> bool:
    """Run auto-fix loop. Returns True if eventually succeeded."""
    for attempt in range(MAX_RUN_RETRIES):
        _emit(session, "log", message=f"Auto-fix attempt {attempt + 1}/{MAX_RUN_RETRIES}…")
        try:
            fixed_code = fix_step_code(step, code, error, system_prompt, llm)
            step.code = fixed_code
            result = _run_sandbox(step, file_map, fixed_code)
            code = fixed_code

            if result["success"]:
                step.status = "completed"
                step.exec_time = result["elapsed"]
                step.exec_stdout = result["stdout"]
                _register_outputs(step, result["output_paths"], file_map, all_outputs)

                map_path = _try_render_map(step.name, result["output_paths"], out_dir)
                _emit(session, "step_success",
                      step_id=step.id, step_name=step.name,
                      elapsed=round(result["elapsed"], 1),
                      stdout=result["stdout"].strip()[:400],
                      output_files=list(result["output_paths"].keys()),
                      map_path=map_path,
                      code=step.code)

                session.status = "awaiting"
                _emit(session, "step_await", step_id=step.id,
                      options=["next", "abort"], has_map=bool(map_path))
                d = _wait(session)
                if d == "abort":
                    session.status = "done"
                    _emit(session, "aborted")
                    return False
                return True
            else:
                error = result["error"]
                _emit(session, "log", message=f"Fix attempt {attempt + 1} failed")
        except Exception as e:
            _emit(session, "log", message=f"Fix error: {e}")

    _emit(session, "log", message="All fix attempts exhausted.")
    session.status = "awaiting"
    _emit(session, "step_await", step_id=step.id,
          options=["retry", "abort"], error="Auto-fix exhausted")
    d = _wait(session)
    if d == "abort":
        session.status = "done"
        _emit(session, "aborted")
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_sandbox(step, file_map: dict, code: str) -> dict:
    sandbox = Sandbox()
    needed = {}
    for inp in step.inputs:
        if inp in file_map:
            needed[inp] = file_map[inp]
        else:
            ext = os.path.splitext(inp)[1].lower()
            candidates = [(fn, fp) for fn, fp in file_map.items()
                          if os.path.splitext(fn)[1].lower() == ext and os.path.isfile(fp)]
            if len(candidates) == 1:
                needed[inp] = candidates[0][1]
    for fn, fp in file_map.items():
        if fn not in needed and os.path.isfile(fp):
            needed[fn] = fp
    try:
        sandbox.setup_inputs(needed)
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": "",
                "output_files": [], "output_paths": {}, "elapsed": 0,
                "error": f"Input setup: {e}"}
    result = sandbox.execute(code)
    output_paths = sandbox.get_all_output_paths()
    return {**result, "output_files": list(output_paths.keys()), "output_paths": output_paths}


def _register_outputs(step, output_paths, file_map, all_outputs):
    for fname, fpath in output_paths.items():
        file_map[fname] = fpath
        all_outputs[fname] = fpath
    for planned in step.outputs:
        if planned not in file_map:
            ext = os.path.splitext(planned)[1].lower()
            matches = [fp for fn, fp in output_paths.items()
                       if os.path.splitext(fn)[1].lower() == ext]
            if len(matches) == 1:
                file_map[planned] = matches[0]


def _try_render_map(step_name, output_paths, out_dir) -> Optional[str]:
    try:
        from geodb.agent_factory.maps.renderer import render_step_map
        return render_step_map(step_name, output_paths, out_dir)
    except Exception:
        return None
