"""
Agent 2 — SQL Verifier
Two stages:
  1. Static analysis (instant, no LLM)
  2. LLM semantic check (correct columns, logic, intent)
"""
import re
from geodb.nl_search.config import SCHEMA_CONTEXT, SAFE_ROW_LIMIT, BLOCKED_KEYWORDS


SYSTEM = """\
You are a SQL auditor for a geospatial SQLite database.
You receive a SQL query and the user's original question.

CRITICAL FACTS ABOUT THIS DATABASE — DO NOT FLAG THESE AS ISSUES:
  • There are NO geometry columns. The metadata table stores ONLY bounding-box
    coordinates (bbox_minx/miny/maxx/maxy). There is no `geom` column,
    no WKB/WKT, no GEOMETRY type.
  • Spatial functions like ST_Intersects, ST_GeomFromText, ST_Within, ST_Contains,
    ST_Distance MUST NOT be used. They will fail because there are no geometries
    to operate on. NEVER suggest them in FIXED_SQL.
  • The CORRECT and ONLY way to test spatial overlap / intersection / "common area"
    between two files is bounding-box overlap:
        a.bbox_minx <= b.bbox_maxx AND a.bbox_maxx >= b.bbox_minx
        AND a.bbox_miny <= b.bbox_maxy AND a.bbox_maxy >= b.bbox_miny
    Treat this as fully valid — do NOT complain that "it only checks bboxes"
    or that "it doesn't ensure actual geometry intersection". BBox overlap IS
    the answer for this database.
  • For "files overlapping with file X", a self-join of files+metadata twice
    (one alias for X, one for candidates) with the bbox-overlap predicate above
    and `f2.id != f1.id` is the canonical correct pattern. PASS it.
  • For filename matching, `f.filename LIKE '%name%'` is correct.

Check ONLY these things:
  1. Valid SELECT (no DML/DDL).
  2. Only tables: files, metadata, file_tags, file_geometry_types, metadata_fts.
  3. Correct column names (those listed in the schema above).
  4. Has LIMIT.
  5. Correct JOINs (files.id = metadata.file_id).
  6. Logically answers the user's question (using bbox overlap where spatial).

If the query is correct, respond PASS even if you can imagine a "more precise"
version. Do not invent issues. Do not request ST_* functions.

Respond EXACTLY as:
VERDICT: PASS
ISSUES: none

  — or —

VERDICT: FAIL
ISSUES: <list>
FIXED_SQL:
```sql
<corrected query>
```
"""


# ── Stage 1: static ──────────────────────────────────────────────────────────

def static_check(sql: str) -> dict:
    """Instant deterministic checks. Returns {passed, issues, fixed_sql}."""
    result = {"passed": True, "issues": [], "fixed_sql": None}
    up = sql.upper().strip()

    for kw in BLOCKED_KEYWORDS:
        if kw in up:
            return {"passed": False,
                    "issues": [f"Blocked keyword: {kw.strip()}"],
                    "fixed_sql": None}

    if not up.startswith("SELECT"):
        return {"passed": False,
                "issues": ["Must start with SELECT"],
                "fixed_sql": None}

    # Strip temporal/ingested_at filters — year filtering is handled by shard targeting
    cleaned = _strip_temporal_filters(sql)
    if cleaned != sql:
        result["issues"].append("Removed temporal/ingested_at filter — year handled by shard targeting")
        result["fixed_sql"] = cleaned
        sql = cleaned

    if "LIMIT" not in sql.upper():
        result["issues"].append("Missing LIMIT — auto-added")
        result["fixed_sql"] = (result["fixed_sql"] or sql).rstrip().rstrip(";") + f" LIMIT {SAFE_ROW_LIMIT}"

    return result


def _strip_temporal_filters(sql: str) -> str:
    """Remove WHERE/AND clauses that filter on temporal_start, temporal_end, or ingested_at.

    These columns are mostly NULL; year filtering is done by shard targeting instead.
    """
    # Patterns to remove: conditions involving these columns
    # Handles: column BETWEEN ... AND ..., column >= ..., column LIKE ..., etc.
    temporal_cols = r'(?:m\.)?temporal_(?:start|end)|(?:f\.)?ingested_at'

    # Remove "AND <temporal_condition>" (when it's not the first condition)
    sql = re.sub(
        r'\s+AND\s+' + temporal_cols + r'\s+(?:BETWEEN\s+\S+\s+AND\s+\S+|[><=!]+\s*\S+|LIKE\s+\S+|IS\s+(?:NOT\s+)?NULL)',
        '', sql, flags=re.IGNORECASE
    )

    # Remove "<temporal_condition> AND" (when it's the first condition in WHERE)
    sql = re.sub(
        r'(' + temporal_cols + r')\s+(?:BETWEEN\s+\S+\s+AND\s+\S+|[><=!]+\s*\S+|LIKE\s+\S+|IS\s+(?:NOT\s+)?NULL)\s+AND\s+',
        '', sql, flags=re.IGNORECASE
    )

    # If WHERE clause is now empty (only had temporal conditions), remove WHERE
    sql = re.sub(
        r'\bWHERE\s+(' + temporal_cols + r')\s+(?:BETWEEN\s+\S+\s+AND\s+\S+|[><=!]+\s*\S+|LIKE\s+\S+|IS\s+(?:NOT\s+)?NULL)\s*',
        '', sql, flags=re.IGNORECASE
    )

    # Clean up any dangling empty WHERE
    sql = re.sub(r'\bWHERE\s+(?=LIMIT|ORDER|GROUP|$)', '', sql, flags=re.IGNORECASE)

    return sql


# ── Stage 2: LLM ─────────────────────────────────────────────────────────────

def llm_check(sql: str, user_query: str, llm) -> dict:
    prompt = f"""{SCHEMA_CONTEXT}

USER QUERY: {user_query}

GENERATED SQL:
```sql
{sql}
```

Verify. Respond with VERDICT, ISSUES, FIXED_SQL."""

    raw = llm.generate(prompt, system=SYSTEM, temperature=0.05)
    return _parse(raw)


# ── Combined ──────────────────────────────────────────────────────────────────

def run(sql: str, user_query: str, llm) -> dict:
    """Full check: static then LLM. Returns {passed, issues, fixed_sql}."""
    s = static_check(sql)
    if not s["passed"]:
        return s

    check_sql = s["fixed_sql"] or sql

    v = llm_check(check_sql, user_query, llm)

    # Merge
    if v["passed"] and s["fixed_sql"]:
        v["fixed_sql"] = s["fixed_sql"]
    if s["issues"]:
        v["issues"] = s["issues"] + v["issues"]
    return v


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse(text: str) -> dict:
    result = {"passed": False, "issues": [], "fixed_sql": None}

    m = re.search(r'VERDICT:\s*(PASS|FAIL)', text, re.IGNORECASE)
    if m:
        result["passed"] = m.group(1).upper() == "PASS"

    m = re.search(r'ISSUES:\s*(.*?)(?:FIXED_SQL:|$)', text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        if raw.lower() not in ("none", "n/a", ""):
            result["issues"] = [
                l.strip().lstrip("-•* ")
                for l in raw.split("\n")
                if l.strip() and l.strip().lower() not in ("none", "n/a")
            ]

    if not result["passed"]:
        from geodb.nl_search.agents.coder import extract_sql
        fixed = extract_sql(text)
        if fixed and fixed.upper().startswith("SELECT"):
            result["fixed_sql"] = fixed

    return result
