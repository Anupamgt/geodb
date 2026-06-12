"""
CLI for Natural Language Search.

    python -m geodb.nl_search.cli -d ./data -i -v
    python -m geodb.nl_search.cli -d ./data "find all KML near Ropar"
"""
import argparse
import os
import sys
import time

from geodb.nl_search import config
from geodb.nl_search.llm_client import LLMClient
from geodb.nl_search.pipeline import Pipeline
from geodb.nl_search import formatter


def _repl(pipe: Pipeline, show_sql: bool = True):
    print("=" * 64)
    print("  GeoDB — Natural Language Search")
    print(f"  Model : {pipe.llm.model}")
    print(f"  Shards: {pipe.executor.list_years()}")
    print("=" * 64)
    print("  Type a query in plain English.  /help for examples.  /quit to exit.")
    print()

    while True:
        try:
            q = input("🔎 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not q:
            continue

        cmd = q.lower()
        if cmd in ("/quit", "/exit", "/q"):
            print("Bye!"); break
        if cmd == "/sql":
            show_sql = not show_sql
            print(f"  SQL display {'ON' if show_sql else 'OFF'}"); continue
        if cmd == "/shards":
            print(f"  {pipe.executor.list_years()}"); continue
        if cmd == "/help":
            for ex in [
                "find all KML files near Ropar within 10km",
                "show files with polygon geometry",
                "list files near highway NH44 within 5km",
                "find drainage KML files",
                "all files around Chandigarh",
                "show largest files by size",
                "files near river Sutlej within 3km",
                "find DEM files",
                "KML files containing 'Moga' in filename",
                "files between 2024-01-01 and 2024-12-31",
            ]:
                print(f"    • {ex}")
            continue

        t0 = time.time()
        trace = pipe.search(q)
        elapsed = time.time() - t0
        print(formatter.as_text(trace, show_sql=show_sql))
        print(f"\n  ⏱  {elapsed:.1f}s  |  attempts: {len(trace.get('attempts', []))}")
        print()


def main():
    global config  # allow model override

    ap = argparse.ArgumentParser(description="NL search over GeoDB")
    ap.add_argument("query", nargs="*", help="Search query (omit for interactive)")
    ap.add_argument("-d", "--data-dir", default=config.DEFAULT_DATA_DIR)
    ap.add_argument("-i", "--interactive", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-m", "--model", default=None,
                    help=f"Ollama model (default: {config.MODEL_NAME})")
    ap.add_argument("--ollama-url", default=None,
                    help=f"Ollama URL (default: {config.OLLAMA_URL})")
    ap.add_argument("--show-sql", action="store_true", default=True)
    ap.add_argument("-j", "--json", action="store_true")
    args = ap.parse_args()

    if args.model:
        config.MODEL_NAME = args.model
    if args.ollama_url:
        config.OLLAMA_URL = args.ollama_url

    if not os.path.isdir(args.data_dir):
        print(f"Error: data dir not found: {args.data_dir}")
        print("Run  python -m geodb.cli ingest <path>  first.")
        sys.exit(1)

    llm = LLMClient(model=args.model, base_url=args.ollama_url)

    if not llm.is_available():
        print(f"⚠️  Cannot reach Ollama at {llm.base_url}")
        print("   Start:  ollama serve")
        print("   Pull:   ollama pull qwen2.5-coder:7b")
        sys.exit(1)

    pipe = Pipeline(args.data_dir, llm=llm, verbose=args.verbose)

    if args.interactive or not args.query:
        _repl(pipe, show_sql=args.show_sql)
    else:
        query = " ".join(args.query)
        trace = pipe.search(query)
        if args.json:
            print(formatter.as_json(trace))
        else:
            print(formatter.as_text(trace, show_sql=args.show_sql))


if __name__ == "__main__":
    main()
