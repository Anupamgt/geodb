"""
Orchestrator — drives the full transformation pipeline.

Flow:
  1. Inspect uploaded files
  2. Planner generates step plan
  3. User approves/edits plan
  4. For each step:
     a. Coder generates code
     b. Verifier checks code (retry loop)
     c. Runner executes in sandbox
     d. Fixer repairs if execution fails (retry loop)
     e. Visualizer generates interactive HTML
     f. User approves, retries, or edits
  5. Save pipeline as template (optional)
"""
import os
import shutil
import time

from geodb.transform.config import (
    OUTPUT_DIR, MAX_CODER_RETRIES, MAX_FIXER_RETRIES, MAX_VIZ_RETRIES,
)
from geodb.transform.llm_client import LLMClient
from geodb.transform.pipeline.step import Step, StepPlan
from geodb.transform.pipeline.runner import run_step
from geodb.transform.agents import planner, coder, verifier, fixer, visualizer
from geodb.transform.storage import examples, template
from geodb.transform.visualizer.renderer import save_step_viz, open_in_browser, generate_pipeline_report


class Orchestrator:
    """Drives the full pipeline with user interaction."""

    def __init__(self, files: list, llm: LLMClient = None,
                 output_dir: str = None, verbose: bool = False):
        """
        Args:
            files: list of file paths to process
            llm: LLMClient (creates default if None)
            output_dir: where to write final outputs
            verbose: show detailed agent trace
        """
        self.llm = llm or LLMClient()
        self.output_dir = output_dir or OUTPUT_DIR
        self.verbose = verbose

        # Inspect files
        self.file_infos = []
        for fp in files:
            info = planner.inspect_file(fp)
            info["path"] = os.path.abspath(fp)
            self.file_infos.append(info)

        # State
        self.plan = None
        self.steps = []
        self.file_map = {}        # { filename: actual_path } across all steps
        self.completed = []       # completed step IDs

        # Ensure builtin examples exist
        examples.ensure_builtins()

    # ── Phase 1: Planning ─────────────────────────────────────────────

    def create_plan(self, task: str) -> StepPlan:
        """Generate a step plan from the task description."""
        self._log("🔍 Searching for matching examples…")
        input_types = [f["type"] for f in self.file_infos]
        matching = examples.find_matching(task, input_types)
        if matching:
            self._log(f"   Found {len(matching)} matching example(s)")

        self._log("📋 Planner agent generating step plan…")
        self.plan = planner.run(task, self.file_infos, self.llm, matching)
        self.steps = self.plan.steps

        # Build initial file map from uploaded files
        self.file_map = {}
        for info in self.file_infos:
            self.file_map[info["name"]] = info["path"]

        return self.plan

    def get_plan_display(self) -> str:
        """Format the plan for display."""
        if not self.plan:
            return "(no plan)"
        lines = [f"\n📋 Plan: {self.plan.task}"]
        lines.append(f"   Output: {self.plan.output.get('format', '?')} — "
                     f"{self.plan.output.get('description', '')}")
        if self.plan.parameters:
            lines.append(f"   Parameters: {self.plan.parameters}")
        lines.append("")
        for step in self.steps:
            lines.append(f"   {step.id}. {step.name}")
            lines.append(f"      {step.description}")
            lines.append(f"      in: {step.inputs} → out: {step.outputs}")
        return "\n".join(lines)

    # ── Phase 2: Execute steps ────────────────────────────────────────

    def execute_step(self, step: Step) -> dict:
        """
        Full cycle for one step: code → verify → run → fix → viz.
        Returns { success, step, viz_path }.
        """
        step.status = "running"
        self._log(f"\n━━━ Step {step.id}/{len(self.steps)}: {step.name} ━━━")

        # ── Generate + verify code ─────────────────────────────
        code = self._generate_code(step)
        if not code:
            step.status = "failed"
            step.error = "Failed to generate valid code"
            return {"success": False, "step": step, "viz_path": ""}

        step.code = code
        step.verified = True

        # ── Execute in sandbox ──────────────────────────────────
        result = self._execute_with_retries(step)
        if not result["success"]:
            step.status = "failed"
            step.error = result["error"]
            return {"success": False, "step": step, "viz_path": ""}

        # Update state
        step.status = "completed"
        step.exec_time = result["elapsed"]
        step.exec_stdout = result["stdout"]
        step.output_metadata = result["output_metadata"]
        self.completed.append(step.id)

        # Register output files for downstream steps
        for fname, fpath in result["output_files"].items():
            # Copy to output dir
            dst = os.path.join(self.output_dir, fname)
            os.makedirs(self.output_dir, exist_ok=True)
            shutil.copy2(fpath, dst)
            self.file_map[fname] = dst

        # ── Visualize ──────────────────────────────────────────
        viz_path = self._visualize_step(step, result["output_metadata"])
        step.viz_html_path = viz_path

        return {"success": True, "step": step, "viz_path": viz_path}

    def _generate_code(self, step: Step) -> str:
        """Coder → Verifier loop. Returns verified code or empty string."""
        plan_ctx = {
            "task": self.plan.task,
            "parameters": self.plan.parameters,
            "previous_steps": [
                {
                    "name": s.name, "description": s.description,
                    "code": s.code, "outputs": s.outputs,
                }
                for s in self.steps if s.id in self.completed
            ],
        }

        current_code = None

        for attempt in range(1, MAX_CODER_RETRIES + 1):
            try:
                if current_code is None:
                    self._log(f"   🤖 Coder (attempt {attempt}): generating…")
                    current_code = coder.run(step, plan_ctx, self.llm)
                else:
                    self._log(f"   🤖 Using verifier's fix (attempt {attempt})")

                self._log(f"   🔍 Verifier: checking…")
                v = verifier.run(current_code, step, plan_ctx, self.llm)

                if v["passed"]:
                    self._log("   ✅ Code verified")
                    return v.get("fixed_code") or current_code

                self._log(f"   ❌ Verification failed: {v['issues']}")
                current_code = v.get("fixed_code")  # None → coder regenerates

            except Exception as e:
                self._log(f"   ⚠️  Error: {e}")
                current_code = None

        return ""

    def _execute_with_retries(self, step: Step) -> dict:
        """Execute step, use fixer on failure."""
        self._log(f"   ⚡ Executing…")

        result = run_step(step, self.file_map)

        if result["success"]:
            self._log(f"   ✅ Done in {result['elapsed']:.1f}s — "
                     f"outputs: {list(result['output_files'].keys())}")
            if result["stdout"].strip():
                self._log(f"   📤 {result['stdout'].strip()[:200]}")
            return result

        # Execution failed → fixer
        for fix_attempt in range(1, MAX_FIXER_RETRIES + 1):
            self._log(f"   ❌ Execution failed: {result['error'][:150]}")
            self._log(f"   🔧 Fixer (attempt {fix_attempt}): repairing…")

            try:
                fixed_code = fixer.run(step.code, result["error"], step, self.llm)
                step.code = fixed_code
                step.retries += 1

                self._log(f"   ⚡ Re-executing…")
                result = run_step(step, self.file_map)

                if result["success"]:
                    self._log(f"   ✅ Fixed! Done in {result['elapsed']:.1f}s")
                    return result

            except Exception as e:
                self._log(f"   ⚠️  Fixer error: {e}")

        return result

    def _visualize_step(self, step: Step, output_meta: dict) -> str:
        """Generate and save visualization for a step."""
        if not output_meta:
            return ""

        self._log(f"   🎨 Visualizer: generating…")

        try:
            viz_result = visualizer.run(step, output_meta, self.llm)
            html = viz_result["html"]
            step.viz_summary = viz_result["summary"]
        except Exception as e:
            self._log(f"   ⚠️  Viz LLM failed ({e}), using fallback")
            viz_result = visualizer.generate_fallback(step, output_meta)
            html = viz_result["html"]
            step.viz_summary = viz_result["summary"]

        viz_path = save_step_viz(step.id, step.name, html, self.output_dir)
        self._log(f"   🗺️  Viz saved: {viz_path}")
        return viz_path

    # ── Phase 3: Save ─────────────────────────────────────────────────

    def save_template(self, template_id: str = None) -> str:
        """Save the completed pipeline as a reusable template."""
        tid = template.save(self.plan, self.steps, template_id)
        self._log(f"💾 Template saved: {tid}")
        return tid

    def generate_report(self) -> str:
        """Generate the combined pipeline report."""
        path = generate_pipeline_report(self.plan.task, self.steps, self.output_dir)
        self._log(f"📊 Report saved: {path}")
        return path

    # ── Replay ────────────────────────────────────────────────────────

    @classmethod
    def replay(cls, template_id: str, files: list, param_overrides: dict = None,
               llm: LLMClient = None, output_dir: str = None,
               interactive: bool = False, verbose: bool = False):
        """
        Re-run a saved pipeline on new files.
        If interactive=True, pause at each step for approval.
        """
        plan, steps = template.load_as_plan(template_id)

        if param_overrides:
            plan.parameters.update(param_overrides)

        orch = cls(files, llm=llm, output_dir=output_dir, verbose=verbose)
        orch.plan = plan
        orch.steps = steps

        # Map uploaded files to expected input names
        # (match by type)
        required = plan.input_files
        for req in required:
            for info in orch.file_infos:
                if info["type"] == req.get("type") and info["name"] not in orch.file_map:
                    orch.file_map[info["name"]] = info["path"]
                    # Also map the expected template name
                    expected_names = [s_inp for s in steps for s_inp in s.inputs
                                    if s_inp.endswith(f".{req['type']}")]
                    for en in expected_names:
                        if en not in orch.file_map:
                            orch.file_map[en] = info["path"]

        for step in steps:
            if interactive:
                print(f"\n━━━ Step {step.id}: {step.name} ━━━")
                print(f"   {step.description}")
                choice = input("   [R]un / [S]kip / [A]bort? > ").strip().lower()
                if choice == "s":
                    step.status = "skipped"
                    continue
                if choice == "a":
                    break

            result = orch.execute_step(step)
            if not result["success"] and interactive:
                choice = input("   Step failed. [R]etry / [S]kip / [A]bort? > ").strip().lower()
                if choice == "r":
                    result = orch.execute_step(step)
                elif choice == "a":
                    break

        return orch

    # ── Helpers ────────────────────────────────────────────────────────

    def _log(self, msg: str):
        if self.verbose:
            print(f"  {msg}")
