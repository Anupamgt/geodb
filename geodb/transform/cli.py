"""
CLI for the Geospatial Transformation Pipeline.

Usage:
    python -m geodb.transform run --files area.kml dem.tif
    python -m geodb.transform replay dem_height_grid --files new_area.kml new_dem.tif
    python -m geodb.transform list-templates
    python -m geodb.transform list-examples
"""
import argparse
import os
import sys
import time

from geodb.transform import config
from geodb.transform.config import save_config, _load_saved, CONFIG_FILE
from geodb.transform.llm_client import LLMClient
from geodb.transform.pipeline.orchestrator import Orchestrator
from geodb.transform.storage import template, examples
from geodb.transform.visualizer.renderer import open_in_browser


def _make_llm(args) -> LLMClient:
    """Build LLMClient from CLI args, warn if unavailable."""
    llm = LLMClient(model=getattr(args, "model", None),
                    base_url=getattr(args, "ollama_url", None))
    if not llm.is_available():
        if llm.using_cloud:
            print("⚠️  Cloud API key is set but provider may be unreachable. Continuing anyway.")
        else:
            print(f"⚠️  Cannot reach Ollama at {llm._ollama_url}")
            print("   Start: ollama serve  |  Pull: ollama pull qwen2.5-coder:7b")
            print("   Or set a cloud API key: python -m geodb.transform config --help")
            sys.exit(1)
    return llm


def cmd_config(args):
    """Show or update the saved LLM config."""
    # --show
    if args.show or (not args.provider and not args.api_key
                     and not args.model and not args.clear):
        saved = _load_saved()
        if not saved:
            print("No saved config. Using defaults (Ollama / env vars).")
        else:
            print(f"\nSaved config  ({CONFIG_FILE}):")
            provider = saved.get("cloud_provider", "openai")
            model    = saved.get("cloud_model",    "gpt-4o-mini")
            key      = saved.get("cloud_api_key",  "")
            masked   = (key[:8] + "..." + key[-4:]) if len(key) > 12 else ("set" if key else "not set")
            print(f"  provider : {provider}")
            print(f"  model    : {model}")
            print(f"  api_key  : {masked}")
        return

    # --clear
    if args.clear:
        import pathlib
        pathlib.Path(CONFIG_FILE).unlink(missing_ok=True)
        print("✅ Saved config cleared. Will fall back to env vars / Ollama.")
        return

    # --provider / --api-key / --model
    updates = {}
    if args.provider:
        updates["cloud_provider"] = args.provider
        if args.provider == "groq":
            updates["cloud_base_url"] = "https://api.groq.com/openai/v1"
        elif args.provider == "gemini":
            updates["cloud_base_url"] = "https://generativelanguage.googleapis.com/v1beta/openai"
            if not args.model:
                updates["cloud_model"] = "gemini-2.5-flash"
        elif args.provider in ("openai", "anthropic"):
            updates["cloud_base_url"] = ""
    if args.api_key:
        updates["cloud_api_key"] = args.api_key
    if args.model:
        updates["cloud_model"] = args.model

    if updates:
        save_config(updates)
        print("✅ Config saved:")
        for k, v in updates.items():
            display = v if "key" not in k else (v[:8] + "..." + v[-4:] if len(v) > 12 else v)
            print(f"   {k} = {display}")
        print(f"\nActive for all future runs (stored in {CONFIG_FILE})")


def cmd_run(args):
    """Interactive pipeline run."""
    llm = _make_llm(args)

    # Validate files
    for f in args.files:
        if not os.path.isfile(f):
            print(f"Error: file not found: {f}")
            sys.exit(1)

    orch = Orchestrator(args.files, llm=llm, output_dir=args.output,
                        verbose=args.verbose)

    # Show file info
    print("\n📁 Files loaded:")
    for info in orch.file_infos:
        meta = info.get("metadata", {})
        desc = f"   {info['name']}  ({info['type']}, {info['size']/1024:.1f} KB)"
        if meta.get("feature_count"):
            desc += f"  {meta['feature_count']} features"
        if meta.get("bands"):
            desc += f"  {meta['bands']} bands"
        print(desc)

    # Get task description
    if args.task:
        task = args.task
    else:
        print("\n📝 Describe what you want to do:")
        task = input("> ").strip()
        if not task:
            print("No task provided. Exiting.")
            return

    # Generate plan
    plan = orch.create_plan(task)
    print(orch.get_plan_display())

    # Approve plan
    if not args.auto:
        while True:
            choice = input("\n   [A]pprove plan / [R]egenerate / [Q]uit > ").strip().lower()
            if choice == "a":
                break
            elif choice == "r":
                plan = orch.create_plan(task)
                print(orch.get_plan_display())
            elif choice == "q":
                print("Aborted.")
                return
            else:
                print("   Choose A, R, or Q")

    # Execute steps
    total_start = time.time()

    for step in orch.steps:
        result = orch.execute_step(step)

        # Show terminal summary
        if step.viz_summary:
            print(f"   📊 Output:")
            print(step.viz_summary)

        if not args.auto:
            if result["success"]:
                while True:
                    prompt = "   [N]ext / [R]etry / [V]iew code"
                    if step.viz_html_path:
                        prompt += " / [M]ap (open viz)"
                    prompt += " / [A]bort > "
                    choice = input(prompt).strip().lower()

                    if choice == "n":
                        break
                    elif choice == "r":
                        result = orch.execute_step(step)
                        if step.viz_summary:
                            print(f"   📊 Output:")
                            print(step.viz_summary)
                    elif choice == "v":
                        print(f"\n--- code ---\n{step.code}\n--- end ---\n")
                    elif choice == "m" and step.viz_html_path:
                        open_in_browser(step.viz_html_path)
                    elif choice == "a":
                        print("Aborted.")
                        return
                    else:
                        print("   Choose N, R, V, M, or A")
            else:
                print(f"   ❌ Step failed: {step.error[:200]}")
                choice = input("   [R]etry / [S]kip / [A]bort > ").strip().lower()
                if choice == "r":
                    result = orch.execute_step(step)
                elif choice == "a":
                    print("Aborted.")
                    return
                # 's' = skip, continue

    total_elapsed = time.time() - total_start

    # Summary
    completed = [s for s in orch.steps if s.status == "completed"]
    failed = [s for s in orch.steps if s.status == "failed"]
    print(f"\n{'='*50}")
    print(f"✅ {len(completed)} steps completed, {len(failed)} failed  "
          f"({total_elapsed:.1f}s total)")

    # Show output files
    if os.path.isdir(orch.output_dir):
        out_files = [f for f in os.listdir(orch.output_dir)
                    if os.path.isfile(os.path.join(orch.output_dir, f))]
        if out_files:
            print(f"\n📦 Output files in {orch.output_dir}/:")
            for f in sorted(out_files):
                size = os.path.getsize(os.path.join(orch.output_dir, f))
                print(f"   {f}  ({size/1024:.1f} KB)")

    # Generate report
    if completed:
        report_path = orch.generate_report()
        print(f"\n📊 Pipeline report: {report_path}")

    # Save template
    if completed and not args.auto:
        choice = input("\n💾 Save this pipeline for reuse? [Y/n] > ").strip().lower()
        if choice != "n":
            name = input("   Template name: ").strip()
            if name:
                tid = orch.save_template(name)
                print(f"   ✅ Saved as '{tid}'")
                print(f"   Replay: python -m geodb.transform replay {tid} "
                      f"--files <new_files>")
    elif completed and args.auto:
        # Auto-save with generated name
        orch.save_template()


def cmd_replay(args):
    """Replay a saved pipeline on new files."""
    llm = _make_llm(args)

    for f in args.files:
        if not os.path.isfile(f):
            print(f"Error: file not found: {f}")
            sys.exit(1)

    # Parse param overrides
    overrides = {}
    if args.param:
        for p in args.param:
            if "=" in p:
                k, v = p.split("=", 1)
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError:
                    pass
                overrides[k] = v

    print(f"📋 Loading template: {args.template}")
    orch = Orchestrator.replay(
        args.template, args.files,
        param_overrides=overrides,
        llm=llm, output_dir=args.output,
        interactive=args.interactive,
        verbose=args.verbose,
    )

    completed = [s for s in orch.steps if s.status == "completed"]
    print(f"\n✅ {len(completed)}/{len(orch.steps)} steps completed")

    if os.path.isdir(orch.output_dir):
        for f in sorted(os.listdir(orch.output_dir)):
            fp = os.path.join(orch.output_dir, f)
            if os.path.isfile(fp):
                print(f"   📦 {f}  ({os.path.getsize(fp)/1024:.1f} KB)")


def cmd_list_templates(args):
    """List saved templates."""
    templates = template.list_templates()
    if not templates:
        print("No saved templates. Run 'python -m geodb.transform run' first.")
        return
    print(f"\n{'ID':<30} {'Task':<40} {'Steps':>5} {'Inputs':<15} {'Created':<20}")
    print("-" * 110)
    for t in templates:
        print(f"{t['id']:<30} {t['task'][:38]:<40} {t['steps']:>5} "
              f"{','.join(t['inputs']):<15} {t['created'][:19]:<20}")


def cmd_list_examples(args):
    """List available examples."""
    examples.ensure_builtins()
    exs = examples.list_examples()
    if not exs:
        print("No examples found.")
        return
    print(f"\n{'Name':<30} {'Task':<45} {'Steps':>5} {'Inputs':<15}")
    print("-" * 95)
    for e in exs:
        print(f"{e['name']:<30} {e['task'][:43]:<45} {e['steps']:>5} "
              f"{','.join(str(i) for i in e['inputs']):<15}")


def cmd_add_example(args):
    """Promote a template to an example."""
    try:
        examples.add_from_template(args.from_template, args.name, args.description or "")
        print(f"✅ Example '{args.name}' added from template '{args.from_template}'")
    except FileNotFoundError:
        print(f"Error: template '{args.from_template}' not found")
        sys.exit(1)


def cmd_delete_template(args):
    """Delete a template."""
    if template.delete(args.template):
        print(f"✅ Deleted template: {args.template}")
    else:
        print(f"Template not found: {args.template}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Geospatial Transformation Pipeline")
    sub = ap.add_subparsers(dest="command")

    # run
    p = sub.add_parser("run", help="Run a new transformation")
    p.add_argument("--files", "-f", nargs="+", required=True, help="Input files")
    p.add_argument("--task", "-t", default=None, help="Task description (interactive if omitted)")
    p.add_argument("--output", "-o", default=None, help="Output directory")
    p.add_argument("--auto", action="store_true", help="Skip user approval")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-m", "--model", default=None)
    p.add_argument("--ollama-url", default=None)

    # replay
    p = sub.add_parser("replay", help="Replay a saved pipeline")
    p.add_argument("template", help="Template ID")
    p.add_argument("--files", "-f", nargs="+", required=True)
    p.add_argument("--param", "-p", nargs="*", help="Override params: key=value")
    p.add_argument("--output", "-o", default=None)
    p.add_argument("--interactive", "-i", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-m", "--model", default=None)
    p.add_argument("--ollama-url", default=None)

    # list-templates
    sub.add_parser("list-templates", help="List saved pipeline templates")

    # list-examples
    sub.add_parser("list-examples", help="List available examples")

    # add-example
    p = sub.add_parser("add-example", help="Promote a template to an example")
    p.add_argument("--name", required=True)
    p.add_argument("--description", default=None)
    p.add_argument("--from-template", required=True)

    # delete-template
    p = sub.add_parser("delete-template", help="Delete a saved template")
    p.add_argument("template")

    # config
    p = sub.add_parser("config", help="Set or show the LLM provider / model / API key")
    p.add_argument("--provider", choices=["openai", "anthropic", "groq", "gemini"],
                   help="Cloud provider  (openai | anthropic | groq | gemini)")
    p.add_argument("--api-key", dest="api_key", metavar="KEY",
                   help="API key (sk-... for OpenAI, sk-ant-... for Anthropic)")
    p.add_argument("--model", metavar="MODEL",
                   help="Model name  e.g. gpt-4o  gpt-4o-mini  claude-sonnet-4-6  claude-haiku-4-5-20251001")
    p.add_argument("--show", action="store_true", help="Show current saved config")
    p.add_argument("--clear", action="store_true", help="Remove saved config (revert to env vars / Ollama)")

    args = ap.parse_args()

    if args.command == "config":
        cmd_config(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "replay":
        cmd_replay(args)
    elif args.command == "list-templates":
        cmd_list_templates(args)
    elif args.command == "list-examples":
        cmd_list_examples(args)
    elif args.command == "add-example":
        cmd_add_example(args)
    elif args.command == "delete-template":
        cmd_delete_template(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
