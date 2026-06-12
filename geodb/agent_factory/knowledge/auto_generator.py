"""
Auto Knowledge Generator (Option B) — uses a cloud LLM (GPT, Claude)
to generate high-quality code patterns for unfamiliar file formats.

Flow:
  1. Check if cached knowledge exists for this format/transform
  2. If not, call cloud LLM to generate a knowledge document
  3. Cache the result as a .md file for future runs
  4. Return the knowledge string for prompt injection

The cloud model writes patterns OPTIMIZED for a small local model:
- Explicit, copy-paste-ready code blocks
- No ambiguity, no "you could also..." alternatives
- Exact import statements, exact function calls
- Handles common edge cases inline
"""
import os
import re
import hashlib

from geodb.agent_factory.config import KNOWLEDGE_DIR


# Where auto-generated knowledge files are cached
AUTO_CACHE_DIR = os.path.join(KNOWLEDGE_DIR, "auto_generated")


RESEARCH_SYSTEM = """\
You are a geospatial Python expert writing a REFERENCE CARD for a junior developer.

Your output will be injected into a code-generation prompt for a small (7B parameter) LLM.
The small model will copy your patterns almost verbatim, so they MUST be:

1. COMPLETE — every import, every function call, no pseudocode
2. CORRECT — tested patterns only, no deprecated APIs
3. DEFENSIVE — handle missing data, empty files, encoding issues
4. MINIMAL — only what's needed, no alternatives or explanations

FORMAT YOUR RESPONSE AS MARKDOWN with ```python``` fenced code blocks.
Use these exact section headers:
  ## Parse {format} file
  ## Extract geometries / data
  ## Write output

CRITICAL RULES:
- For XML-based formats: use open(path, 'rb') as f, then etree.parse(f, parser)
  — NEVER pass a path string to etree.parse() (breaks on Windows paths with spaces)
- Always use os.path.join(INPUT_DIR, filename) for reading
- Always use os.path.join(OUTPUT_DIR, filename) for writing
- INPUT_DIR and OUTPUT_DIR are already defined — do NOT redefine them
- Show exact namespace strings for XML formats
- Include coordinate extraction (lon, lat, altitude if present)
- Handle both 2D and 3D coordinates
"""


def generate_knowledge(file_format: str, transformation_type: str,
                       task_description: str, cloud_llm) -> str:
    """
    Generate a knowledge document for an unfamiliar format/transformation.

    Args:
        file_format: input file format (e.g. "gpx", "gml", "osm")
        transformation_type: what we're doing (e.g. "coordinate_extraction")
        task_description: the user's task in plain English
        cloud_llm: CloudLLMClient instance

    Returns:
        Knowledge string (markdown with code blocks), or "" on failure
    """
    # Check cache first
    cached = _load_cached(file_format, transformation_type)
    if cached:
        return cached

    # Build the research prompt
    prompt = f"""Write a Python reference card for:

INPUT FORMAT: .{file_format}
TASK: {task_description}
TRANSFORMATION: {transformation_type}

Include:
1. How to parse/read .{file_format} files in Python (exact library + code)
2. How to extract geometries, coordinates, or data from the parsed structure
3. How to write the result to the output format

Remember: the code will run on Windows. Use file objects for XML parsing, not path strings.
Show complete, runnable code blocks."""

    try:
        raw = cloud_llm.generate(prompt, system=RESEARCH_SYSTEM)
    except Exception as e:
        print(f"  ⚠️  Cloud knowledge generation failed: {e}")
        return ""

    if not raw or len(raw) < 50:
        return ""

    # Clean up the response — keep only the useful parts
    knowledge = _clean_response(raw, file_format)

    # Cache for future use
    _save_cached(knowledge, file_format, transformation_type)

    return knowledge


def has_cached(file_format: str, transformation_type: str = "") -> bool:
    """Check if cached auto-generated knowledge exists."""
    cache_path = _cache_path(file_format, transformation_type)
    return os.path.isfile(cache_path)


def list_cached() -> list:
    """List all cached auto-generated knowledge files."""
    if not os.path.isdir(AUTO_CACHE_DIR):
        return []
    return [f for f in os.listdir(AUTO_CACHE_DIR) if f.endswith(".md")]


def clear_cached(file_format: str = None):
    """Clear cached knowledge — specific format or all."""
    if not os.path.isdir(AUTO_CACHE_DIR):
        return
    if file_format:
        for f in os.listdir(AUTO_CACHE_DIR):
            if f.startswith(f"auto_{file_format}"):
                os.remove(os.path.join(AUTO_CACHE_DIR, f))
    else:
        for f in os.listdir(AUTO_CACHE_DIR):
            if f.endswith(".md"):
                os.remove(os.path.join(AUTO_CACHE_DIR, f))


# ── Internal helpers ─────────────────────────────────────────────────────────

def _cache_path(file_format: str, transformation_type: str) -> str:
    """Build a deterministic cache filename."""
    key = f"{file_format}_{transformation_type}" if transformation_type else file_format
    # Sanitize for filesystem
    safe_key = re.sub(r'[^a-zA-Z0-9_]', '_', key)
    return os.path.join(AUTO_CACHE_DIR, f"auto_{safe_key}.md")


def _load_cached(file_format: str, transformation_type: str) -> str:
    """Load cached knowledge if it exists."""
    path = _cache_path(file_format, transformation_type)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _save_cached(knowledge: str, file_format: str, transformation_type: str):
    """Save generated knowledge to cache."""
    os.makedirs(AUTO_CACHE_DIR, exist_ok=True)
    path = _cache_path(file_format, transformation_type)

    header = (
        f"# Auto-generated knowledge: {file_format}\n"
        f"# Transformation: {transformation_type}\n"
        f"# Generated by cloud LLM — cached for reuse\n\n"
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(header + knowledge)


def _clean_response(raw: str, file_format: str) -> str:
    """
    Clean the cloud LLM response to keep only actionable patterns.
    Remove conversational fluff, keep code blocks and section headers.
    """
    lines = raw.split("\n")
    cleaned = []
    in_code = False

    for line in lines:
        # Always keep code blocks
        if line.strip().startswith("```"):
            in_code = not in_code
            cleaned.append(line)
            continue

        if in_code:
            cleaned.append(line)
            continue

        # Keep section headers
        if line.strip().startswith("#"):
            cleaned.append(line)
            continue

        # Keep lines with useful content markers
        stripped = line.strip()
        if stripped and (
            stripped.startswith("-") or
            stripped.startswith("*") or
            stripped.startswith("Note:") or
            stripped.startswith("IMPORTANT:") or
            stripped.startswith("WARNING:") or
            "import " in stripped or
            "install " in stripped or
            len(stripped) < 100  # short informational lines
        ):
            cleaned.append(line)
            continue

        # Skip verbose explanation paragraphs
        if len(stripped) > 100:
            continue

        cleaned.append(line)

    return "\n".join(cleaned).strip()
