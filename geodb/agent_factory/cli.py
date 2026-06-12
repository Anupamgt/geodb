"""
CLI for Agent Factory.

    python -m geodb.agent_factory create -t "task" -f file1 file2 -v
    python -m geodb.agent_factory create -t "task" -ei ex1 ex2 -eo expected.xlsx -f actual1 actual2
    python -m geodb.agent_factory run my_agent -f file1 file2
    python -m geodb.agent_factory list
"""
import argparse
import os
import sys
import time

from geodb.agent_factory import config
from geodb.agent_factory.llm_client import LLMClient
from geodb.agent_factory.creation.agent_creator import create_agent
from geodb.agent_factory.runtime.step_runner import run_steps_interactive, run_steps_auto
from geodb.agent_factory.analysis.file_inspector import inspect
from geodb.agent_factory.storage import agent_store


# ── CREATE ────────────────────────────────────────────────────────────────────

def cmd_create(args):
    """Create a new agent and execute step-by-step."""
    llm = _get_llm(args)

    has_examples = args.example_input and args.example_output
    has_files = bool(args.files)

    if not has_examples and not has_files:
        print("Error: provide --example-input + --example-output, or --files, or both.")
        sys.exit(1)

    all_paths = (args.example_input or []) + (args.files or [])
    if args.example_output:
        all_paths.append(args.example_output)
    for f in all_paths:
        if not os.path.isfile(f):
            print(f"Error: file not found: {f}")
            sys.exit(1)

    # Show file info
    if has_examples:
        print("\n📁 Example Inputs:")
        for f in args.example_input:
            _print_file_info(f)
        print(f"\n📊 Example Output:")
        _print_file_info(args.example_output)

    run_files = args.files if has_files else (args.example_input or [])
    print(f"\n📁 Files to process:")
    for f in run_files:
        _print_file_info(f)

    print(f"\n📝 Task: {args.task}")
    if not has_examples:
        print("   (no examples — agent will be inferred from task + files)")

    # Phase 1: Create agent spec with steps
    print(f"\n{'=' * 60}")
    print("  PHASE 1: Creating specialist agent…")
    print(f"{'=' * 60}")

    t0 = time.time()
    spec = create_agent(
        task=args.task,
        example_inputs=args.example_input if has_examples else None,
        example_output=args.example_output if has_examples else None,
        files=run_files if not has_examples else None,
        llm=llm, agent_id=args.name, verbose=args.verbose,
    )
    create_time = time.time() - t0
    print(f"\n  ✅ Agent '{spec.agent_id}' created in {create_time:.1f}s")
    print(f"     {len(spec.steps)} steps planned:")
    for s in spec.steps:
        print(f"       {s.id}. {s.name}: {s.description[:70]}")

    # Approve plan
    choice = input("\n  [A]pprove plan / [R]egenerate / [Q]uit > ").strip().lower()
    if choice == "q":
        print("  Aborted.")
        return
    elif choice == "r":
        spec = create_agent(
            task=args.task,
            example_inputs=args.example_input if has_examples else None,
            example_output=args.example_output if has_examples else None,
            files=run_files if not has_examples else None,
            llm=llm, agent_id=args.name, verbose=args.verbose,
        )
        print(f"\n  ✅ Regenerated — {len(spec.steps)} steps:")
        for s in spec.steps:
            print(f"       {s.id}. {s.name}: {s.description[:70]}")

    # Phase 2: Execute step-by-step with user validation
    print(f"\n{'=' * 60}")
    print("  PHASE 2: Executing step-by-step…")
    print(f"{'=' * 60}")

    output_dir = args.output or config.OUTPUT_DIR
    t0 = time.time()

    if args.auto:
        result = run_steps_auto(spec, run_files, llm, output_dir=output_dir,
                                verbose=args.verbose)
    else:
        result = run_steps_interactive(spec, run_files, llm, output_dir=output_dir,
                                       verbose=args.verbose)

    exec_time = time.time() - t0

    # Summary
    completed = [s for s in spec.steps if s.status == "completed"]
    failed = [s for s in spec.steps if s.status == "failed"]

    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    for s in spec.steps:
        icon = "✅" if s.status == "completed" else "❌" if s.status == "failed" else "⏭️"
        time_str = f" ({s.exec_time:.1f}s)" if s.exec_time else ""
        print(f"  {icon} Step {s.id}: {s.name}{time_str}")
    print(f"\n  {len(completed)}/{len(spec.steps)} steps completed in {exec_time:.1f}s")

    if result.get("aborted"):
        print("  ⚠️  Execution was aborted")

    # Show output files
    if os.path.isdir(output_dir):
        out_files = [f for f in os.listdir(output_dir)
                     if os.path.isfile(os.path.join(output_dir, f))]
        if out_files:
            print(f"\n  📦 Output files ({output_dir}):")
            for f in sorted(out_files):
                size = os.path.getsize(os.path.join(output_dir, f))
                print(f"     {f}  ({size/1024:.1f} KB)")

    # Phase 3: Save agent (only after all steps completed)
    if result["success"]:
        print(f"\n  All steps completed successfully!")
        choice = input("  💾 Save this agent for reuse? [Y/n] > ").strip().lower()
        if choice != "n":
            name = input(f"  Agent name [{spec.agent_id}]: ").strip()
            if name:
                spec.agent_id = name
            agent_id = agent_store.save(spec)
            print(f"  ✅ Saved as '{agent_id}'")
            print(f"  Run later: python -m geodb.agent_factory run {agent_id} -f <files>")
    else:
        choice = input("  Some steps failed. Save agent anyway? [y/N] > ").strip().lower()
        if choice == "y":
            agent_id = agent_store.save(spec)
            print(f"  Saved as '{agent_id}' (with failed steps)")


# ── RUN ───────────────────────────────────────────────────────────────────────

def cmd_run(args):
    """Run an existing agent on new files — step by step."""
    llm = _get_llm(args)

    for f in args.files:
        if not os.path.isfile(f):
            print(f"Error: file not found: {f}")
            sys.exit(1)

    spec = agent_store.load(args.agent)
    print(f"\n📋 Agent: {spec.agent_id}")
    print(f"   {spec.description}")
    print(f"   {len(spec.steps)} steps:")
    for s in spec.steps:
        print(f"     {s.id}. {s.name}: {s.description[:70]}")

    # Reset step statuses for fresh run
    for s in spec.steps:
        s.status = "pending"
        s.code = ""
        s.error = ""
        s.exec_time = 0

    # Parse param overrides
    params = {}
    if args.param:
        for p in args.param:
            if "=" in p:
                k, v = p.split("=", 1)
                try: v = float(v) if "." in v else int(v)
                except ValueError: pass
                params[k] = v

    output_dir = args.output or config.OUTPUT_DIR
    print(f"\n⚡ Executing…\n")

    if args.auto:
        result = run_steps_auto(spec, args.files, llm, params=params,
                                output_dir=output_dir, verbose=args.verbose)
    else:
        result = run_steps_interactive(spec, args.files, llm, params=params,
                                       output_dir=output_dir, verbose=args.verbose)

    # Summary
    completed = [s for s in spec.steps if s.status == "completed"]
    print(f"\n  {len(completed)}/{len(spec.steps)} steps completed")

    if os.path.isdir(output_dir):
        for f in sorted(os.listdir(output_dir)):
            fp = os.path.join(output_dir, f)
            if os.path.isfile(fp):
                print(f"  📦 {f}  ({os.path.getsize(fp)/1024:.1f} KB)")


# ── LIST / INFO / DELETE ──────────────────────────────────────────────────────

def cmd_list(args):
    agents = agent_store.list_agents()
    if not agents:
        print("No agents. Use 'create' first.")
        return
    print(f"\n{'ID':<30} {'Description':<40} {'Steps':>5} {'Output':>8} {'Created':<20}")
    print("-" * 105)
    for a in agents:
        print(f"{a['id']:<30} {a['description'][:38]:<40} {a.get('steps',0):>5} "
              f"{a['output_format']:>8} {a['created'][:19]:<20}")


def cmd_info(args):
    spec = agent_store.load(args.agent)
    print(f"\n📋 Agent: {spec.agent_id} (v{spec.version})")
    print(f"   Task: {spec.description}")
    print(f"   Created: {spec.created}")
    print(f"\n   Inputs:")
    for i in spec.input_spec:
        print(f"     - type: {i['type']}, role: {i['role']}")
    print(f"   Output: {spec.output_spec.get('format','?')} — {spec.output_spec.get('description','')[:60]}")
    if spec.parameters:
        print(f"   Parameters:")
        for k, v in spec.parameters.items():
            d = v.get("default") if isinstance(v, dict) else v
            print(f"     - {k}: {d}")
    print(f"\n   Steps ({len(spec.steps)}):")
    for s in spec.steps:
        print(f"     {s.id}. {s.name}: {s.description[:60]}")
        print(f"        in: {s.inputs} → out: {s.outputs}")
    print(f"\n   Knowledge: {spec.knowledge_used}")
    print(f"   Validation: {len(spec.validation_rules)} rules")


def cmd_delete(args):
    if agent_store.delete(args.agent):
        print(f"✅ Deleted: {args.agent}")
    else:
        print(f"Agent not found: {args.agent}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_file_info(filepath):
    info = inspect(filepath)
    desc = f"   {info['name']}  ({info.get('file_format', info['type'])}"
    if info.get("feature_count"): desc += f", {info['feature_count']} features"
    if info.get("geometry_types"): desc += f", {info['geometry_types']}"
    if info.get("bands"): desc += f", {info['bands']} bands, {info.get('dtype','')}"
    if info.get("data_class"): desc += f", {info['data_class']}"
    if info.get("rows"): desc += f", {info['rows']} rows"
    if info.get("columns"): desc += f", cols: {info['columns']}"
    desc += f", {info['size']/1024:.1f} KB)"
    print(desc)


def _get_llm(args):
    model = getattr(args, "model", None)
    url = getattr(args, "ollama_url", None)
    if model: config.MODEL_NAME = model
    if url: config.OLLAMA_URL = url
    llm = LLMClient(model=model, base_url=url)
    if not llm.is_available():
        print(f"⚠️  Cannot reach Ollama at {llm.base_url}")
        print("   Start: ollama serve  |  Pull: ollama pull qwen2.5-coder:7b")
        sys.exit(1)
    return llm


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Geospatial Agent Factory")
    sub = ap.add_subparsers(dest="command")

    p = sub.add_parser("create", help="Create + run agent step-by-step")
    p.add_argument("--task", "-t", required=True, help="Task description")
    p.add_argument("--example-input", "-ei", nargs="+", default=None, help="Example inputs (optional)")
    p.add_argument("--example-output", "-eo", default=None, help="Expected output (optional)")
    p.add_argument("--files", "-f", nargs="+", default=[], help="Files to process")
    p.add_argument("--name", "-n", default=None, help="Agent name")
    p.add_argument("--output", "-o", default=None, help="Output directory")
    p.add_argument("--auto", action="store_true", help="Skip user prompts")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-m", "--model", default=None)
    p.add_argument("--ollama-url", default=None)

    p = sub.add_parser("run", help="Run saved agent step-by-step")
    p.add_argument("agent", help="Agent ID")
    p.add_argument("--files", "-f", nargs="+", required=True)
    p.add_argument("--param", "-p", nargs="*", help="key=value overrides")
    p.add_argument("--output", "-o", default=None)
    p.add_argument("--auto", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-m", "--model", default=None)
    p.add_argument("--ollama-url", default=None)

    sub.add_parser("list", help="List agents")
    p = sub.add_parser("info", help="Agent details")
    p.add_argument("agent")
    p = sub.add_parser("delete", help="Delete agent")
    p.add_argument("agent")

    args = ap.parse_args()
    cmds = {"create": cmd_create, "run": cmd_run, "list": cmd_list,
            "info": cmd_info, "delete": cmd_delete}
    fn = cmds.get(args.command)
    if fn:
        fn(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
