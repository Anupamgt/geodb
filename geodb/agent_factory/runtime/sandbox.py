"""
Sandbox — isolated execution environment for pipeline step code.
Creates a temp directory, copies inputs, runs code, collects outputs.
"""
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time

from geodb.agent_factory.config import (
    SANDBOX_ROOT, STEP_TIMEOUT, ALLOWED_IMPORTS, BLOCKED_PATTERNS,
)


class SandboxError(Exception):
    pass


class SafetyViolation(SandboxError):
    pass


# ── Static code safety check ─────────────────────────────────────────────────

def check_code_safety(code: str) -> list:
    """
    Scan code for blocked patterns and unauthorized imports.
    Returns list of violation strings (empty = safe).
    """
    violations = []

    # Pattern scan
    for pattern in BLOCKED_PATTERNS:
        if pattern in code:
            violations.append(f"Blocked pattern: {pattern}")

    # AST-based import check
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _check_import(alias.name, violations)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    _check_import(node.module, violations)
    except SyntaxError as e:
        violations.append(f"Syntax error: {e}")

    return violations


def check_undefined_calls(code: str) -> list:
    """
    Detect calls to plain-name functions not defined or imported in the code.
    Returns sorted list of undefined name strings.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    import builtins as _builtins
    defined = set(dir(_builtins))
    defined.update({"INPUT_DIR", "OUTPUT_DIR"})

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname if alias.asname else alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                defined.add(alias.asname if alias.asname else alias.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                _collect_names(target, defined)
        elif isinstance(node, ast.AugAssign):
            _collect_names(node.target, defined)
        elif isinstance(node, ast.AnnAssign) and node.target:
            _collect_names(node.target, defined)
        elif isinstance(node, ast.For):
            _collect_names(node.target, defined)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars:
                    _collect_names(item.optional_vars, defined)

    undefined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in defined:
                undefined.add(node.func.id)

    return sorted(undefined)


def _collect_names(target, defined: set):
    if isinstance(target, ast.Name):
        defined.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _collect_names(elt, defined)


def _check_import(module_name: str, violations: list):
    """Check if a module import is allowed."""
    base = module_name.split(".")[0]
    if module_name in ALLOWED_IMPORTS:
        return
    if base in ALLOWED_IMPORTS:
        return
    if base in ("np", "pd"):
        return
    violations.append(f"Blocked import: {module_name}")


# ── Sandbox execution ─────────────────────────────────────────────────────────

class Sandbox:
    """
    Creates an isolated workspace, runs code, and collects results.
    """

    def __init__(self):
        os.makedirs(SANDBOX_ROOT, exist_ok=True)
        self.workdir = tempfile.mkdtemp(dir=SANDBOX_ROOT, prefix="step_")
        self.input_dir = os.path.join(self.workdir, "inputs")
        self.output_dir = os.path.join(self.workdir, "outputs")
        self.viz_dir = os.path.join(self.workdir, "viz")
        os.makedirs(self.input_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.viz_dir)

    def setup_inputs(self, file_map: dict):
        """
        Copy input files into the sandbox.
        file_map: { 'filename.ext': '/actual/path/to/file' }
        """
        for name, src_path in file_map.items():
            dst = os.path.join(self.input_dir, name)
            if os.path.isfile(src_path):
                shutil.copy2(src_path, dst)
            else:
                raise SandboxError(f"Input file not found: {src_path}")

    def execute(self, code: str, timeout: int = None) -> dict:
        """
        Run code in a subprocess.

        Returns:
            {
                success: bool,
                stdout: str,
                stderr: str,
                output_files: list[str],   # filenames in output_dir
                elapsed: float,
                error: str,
            }
        """
        timeout = timeout or STEP_TIMEOUT

        # Safety check
        violations = check_code_safety(code)
        if violations:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "output_files": [],
                "elapsed": 0.0,
                "error": f"Safety violations: {'; '.join(violations)}",
            }

        # Undefined-name check — catch NameErrors before subprocess launch
        undefined = check_undefined_calls(code)
        if undefined:
            names = ", ".join(f"'{n}'" for n in undefined)
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "output_files": [],
                "elapsed": 0.0,
                "error": (
                    f"NameError (pre-execution): functions called but never defined: {names}. "
                    "Define each function inline before calling it, or replace the call with "
                    "equivalent inline logic."
                ),
            }

        # Wrap code with INPUT_DIR / OUTPUT_DIR setup
        wrapped = _wrap_code(code, self.input_dir, self.output_dir)

        # Write to file
        code_path = os.path.join(self.workdir, "code.py")
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(wrapped)

        # Execute in subprocess
        t0 = time.time()
        try:
            result = subprocess.run(
                [sys.executable, code_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.workdir,
                env={
                    **os.environ,
                    "INPUT_DIR": self.input_dir,
                    "OUTPUT_DIR": self.output_dir,
                },
            )
            elapsed = time.time() - t0

            output_files = []
            if os.path.isdir(self.output_dir):
                # Walk recursively to find outputs in subdirectories too
                for dirpath, _, filenames in os.walk(self.output_dir):
                    for fname in filenames:
                        full = os.path.join(dirpath, fname)
                        # Promote files from subdirs to output_dir root
                        top_dst = os.path.join(self.output_dir, fname)
                        if full != top_dst:
                            shutil.copy2(full, top_dst)
                        output_files.append(fname)

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "output_files": sorted(output_files),
                "elapsed": elapsed,
                "error": result.stderr if result.returncode != 0 else "",
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "output_files": [],
                "elapsed": timeout,
                "error": f"Execution timed out after {timeout}s",
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "output_files": [],
                "elapsed": time.time() - t0,
                "error": str(e),
            }

    def get_output_path(self, filename: str) -> str:
        """Get full path to an output file."""
        return os.path.join(self.output_dir, filename)

    def get_all_output_paths(self) -> dict:
        """Return {filename: full_path} for all output files."""
        result = {}
        if os.path.isdir(self.output_dir):
            for f in os.listdir(self.output_dir):
                fp = os.path.join(self.output_dir, f)
                if os.path.isfile(fp):
                    result[f] = fp
        return result

    def cleanup(self):
        """Remove the sandbox workspace."""
        try:
            shutil.rmtree(self.workdir, ignore_errors=True)
        except Exception:
            pass


def _wrap_code(code: str, input_dir: str, output_dir: str) -> str:
    """Prepend INPUT_DIR / OUTPUT_DIR setup and error handling."""
    # Normalize paths for Windows compatibility
    input_dir_escaped = input_dir.replace("\\", "\\\\")
    output_dir_escaped = output_dir.replace("\\", "\\\\")

    header = f'''\
import os
import warnings
warnings.filterwarnings("ignore")

INPUT_DIR = r"{input_dir}"
OUTPUT_DIR = r"{output_dir}"

'''
    return header + code
