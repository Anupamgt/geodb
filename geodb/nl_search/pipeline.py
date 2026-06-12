"""
Orchestrator:  query → location → coder ↔ verifier loop → executor → results
"""
import re
from geodb.nl_search.config import MAX_RETRIES
from geodb.nl_search.llm_client import LLMClient
from geodb.nl_search import location as loc_mod
from geodb.nl_search.agents import coder, verifier
from geodb.nl_search.executor import Executor
from geodb.nl_search import file_inspector


class Pipeline:

    def __init__(self, data_dir: str, llm: LLMClient = None, verbose: bool = False):
        self.executor = Executor(data_dir)
        self.llm = llm or LLMClient()
        self.verbose = verbose

    def search(self, user_query: str) -> dict:
        trace = {
            "query": user_query,
            "location": None,
            "attempts": [],
            "final_sql": None,
            "results": None,
            "error": None,
        }

        # 1. Location
        location = loc_mod.resolve(user_query)
        trace["location"] = location
        self._log(f"📍 Location: {location}" if location else "📍 No location")

        # 2. Coder ↔ Verifier loop
        current_sql = None

        for attempt in range(1, MAX_RETRIES + 1):
            step = {"n": attempt, "sql": None, "verification": None, "error": None}

            try:
                # Coder
                if current_sql is None:
                    self._log(f"🤖 Coder (attempt {attempt}): generating …")
                    current_sql = coder.run(user_query, location, self.llm)
                else:
                    self._log(f"🤖 Using verifier's fix (attempt {attempt})")

                step["sql"] = current_sql
                self._log(f"📝 SQL: {current_sql[:150]}")

                # Verifier
                self._log("🔍 Verifier: checking …")
                v = verifier.run(current_sql, user_query, self.llm)
                step["verification"] = v

                if v["passed"]:
                    trace["final_sql"] = v.get("fixed_sql") or current_sql
                    trace["attempts"].append(step)
                    self._log("✅ PASSED")
                    break

                self._log(f"❌ FAILED: {v['issues']}")
                current_sql = v.get("fixed_sql")  # None forces coder regen
                trace["attempts"].append(step)

            except Exception as e:
                step["error"] = str(e)
                trace["attempts"].append(step)
                self._log(f"⚠️  Error: {e}")
                current_sql = None

        if trace["final_sql"] is None:
            trace["error"] = "Could not produce valid SQL after all retries"
            return trace

        # 3. Execute (target only relevant year shards when possible)
        target_years = _extract_years(user_query)
        available = self.executor.list_years()
        if target_years:
            target_years = [y for y in target_years if y in available]
        shard_label = f"{len(target_years)} shard(s)" if target_years else f"{len(self.executor.shards)} shard(s)"
        self._log(f"⚡ Executing on {shard_label} …")
        try:
            result = self.executor.run(trace["final_sql"], years=target_years or None)
            trace["results"] = result
            self._log(f"📊 {result['count']} rows from {result['shards']} shard(s)")
            if result["errors"]:
                self._log(f"⚠️  Shard errors: {result['errors']}")
        except Exception as e:
            trace["error"] = f"Execution error: {e}"

        # 4. Optional file-content inspection
        if trace.get("results") and file_inspector.needs_inspection(user_query):
            rows = trace["results"].get("rows", [])
            inspected = 0
            for row in rows[:5]:  # cap to top 5 to avoid huge work
                summary = file_inspector.inspect(row)
                if summary is not None:
                    row["_content"] = summary
                    inspected += 1
            self._log(f"🔬 Inspected {inspected} file(s) for content")

        # 5. Optional coverage / district lookup
        if trace.get("results") and _needs_coverage(user_query):
            rows = trace["results"].get("rows", [])
            tagged = 0
            for row in rows[:20]:
                cov = loc_mod.reverse_lookup(
                    row.get("bbox_minx"), row.get("bbox_miny"),
                    row.get("bbox_maxx"), row.get("bbox_maxy"),
                )
                if cov:
                    row["_coverage"] = cov
                    tagged += 1
            self._log(f"🗺  Coverage lookup for {tagged} file(s)")

        return trace

    def _log(self, msg):
        if self.verbose:
            print(f"  {msg}")


_COVERAGE_KEYWORDS = (
    "which area", "what area", "which district", "what district",
    "which region", "what region", "which city", "what city",
    "where is", "where does", "where it covers", "covers which",
    "what does it cover", "what does this file cover",
    "what does the file cover", "covers what", "coverage", "covered area",
    "located in", "location of", "place of", "similar area",
)


def _needs_coverage(q: str) -> bool:
    ql = q.lower()
    return any(k in ql for k in _COVERAGE_KEYWORDS)


def _extract_years(query: str) -> list:
    """Extract explicit 4-digit years (2000–2099) from the query for shard targeting."""
    return sorted(set(int(y) for y in re.findall(r'\b(20\d{2})\b', query)))
