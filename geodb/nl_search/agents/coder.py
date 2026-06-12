"""
Agent 1 — SQL Coder
Converts natural language + resolved location into a SELECT statement.
"""
import re
from geodb.nl_search.config import SCHEMA_CONTEXT, SAFE_ROW_LIMIT


SYSTEM = """\
You are a SQL expert. Convert the user's natural-language query about geospatial
files (KML / GeoTIFF) into a single SQLite SELECT statement.

OUTPUT FORMAT: only the SQL inside ```sql``` fences. No explanation.

RULES:
- SELECT only. Never DML/DDL.
- Always JOIN files f and metadata m ON f.id = m.file_id
- End with LIMIT.
- File-type keywords (DEM, LULC, drain, contour, SOI …): f.filename LIKE '%keyword%'
- Text search on description/tags: metadata_fts MATCH 'terms'
- Spatial proximity: use bbox expansion with the pre-computed values provided.
- For geometry-type filters: JOIN file_geometry_types g ON f.id = g.file_id WHERE g.geometry_type = 'Polygon'
- For tag filters: JOIN file_tags t ON f.id = t.file_id WHERE t.tag LIKE '%value%'
- Return useful columns: f.id, f.filename, f.file_type, f.file_path, m.bbox_minx, m.bbox_miny, m.bbox_maxx, m.bbox_maxy, m.feature_count, m.layer_names, m.description

OVERLAP-WITH-A-NAMED-FILE PATTERN:
When the user asks which files overlap / intersect / share area / have common area
with a SPECIFIC named file (e.g. "what KML files overlap with DEM_demo", "files
intersecting Moga.kml", "kml that have common area as DEM_dem"), self-join
files + metadata twice — once for the reference file, once for candidates.
Bounding-box overlap test: a.minx <= b.maxx AND a.maxx >= b.minx AND a.miny <= b.maxy AND a.maxy >= b.miny.
Exclude the reference file itself with f2.id != f1.id.

IMPORTANT: There are NO geometry columns in this database — only bbox values.
NEVER use ST_Intersects, ST_GeomFromText, ST_Within, ST_Contains, or any spatial
function. Use ONLY the bbox-overlap predicate above. It is the correct answer.

TEMPORAL / YEAR FILTERING:
The database is SHARDED BY YEAR — each year has its own .db file (e.g. 2026.db).
The pipeline automatically selects the correct shard(s) based on the year in the query.
Therefore, when the user asks for files "of year X", "from 2024", etc.:
- Do NOT add any year/date WHERE clause. Just SELECT all files — the shard
  targeting already ensures only that year's files are returned.
- NEVER filter on f.ingested_at — it is the DB insertion timestamp, not the file's year.
- m.temporal_start / m.temporal_end are often NULL, so do NOT rely on them for year filtering.

Example — "give me all files of year 2026":
```sql
SELECT f.id, f.filename, f.file_type, f.file_path,
       m.bbox_minx, m.bbox_miny, m.bbox_maxx, m.bbox_maxy,
       m.feature_count, m.layer_names, m.description
FROM files f
JOIN metadata m ON f.id = m.file_id
LIMIT 200;
```

FILE-SPECIFIC METADATA PATTERN:
When the user asks about ONE named file ("what is the bbox of X", "how many features
in Moga.kml", "show layers of DEM_demo", "resolution of foo.tif", "tags for bar.kml"),
filter by f.filename LIKE '%name%' and SELECT the requested metadata columns. If they
ask generally ("tell me about X", "show metadata for X"), return all useful columns
from metadata plus filename/file_type/file_path. Use file_tags / file_geometry_types
joins when those specific facets are requested.

Example — "what is the bbox of DEM_demo":
```sql
SELECT f.filename, m.bbox_minx, m.bbox_miny, m.bbox_maxx, m.bbox_maxy
FROM files f
JOIN metadata m ON f.id = m.file_id
WHERE f.filename LIKE '%DEM_demo%'
LIMIT 10;
```

Example — "show me everything about Moga.kml":
```sql
SELECT f.id, f.filename, f.file_type, f.file_path,
       m.bbox_minx, m.bbox_miny, m.bbox_maxx, m.bbox_maxy,
       m.crs_epsg, m.feature_count, m.layer_names, m.geometry_types,
       m.description, m.tags, m.source
FROM files f
JOIN metadata m ON f.id = m.file_id
WHERE f.filename LIKE '%Moga%'
LIMIT 10;
```

Example — "what kml files overlap with DEM_demo":
```sql
SELECT f2.id, f2.filename, f2.file_type, f2.file_path,
       m2.bbox_minx, m2.bbox_miny, m2.bbox_maxx, m2.bbox_maxy,
       m2.feature_count, m2.layer_names, m2.description
FROM files f1
JOIN metadata m1 ON f1.id = m1.file_id
JOIN metadata m2 ON m1.bbox_minx <= m2.bbox_maxx
                AND m1.bbox_maxx >= m2.bbox_minx
                AND m1.bbox_miny <= m2.bbox_maxy
                AND m1.bbox_maxy >= m2.bbox_miny
JOIN files f2 ON f2.id = m2.file_id
WHERE f1.filename LIKE '%DEM_demo%'
  AND f2.file_type = 'kml'
  AND f2.id != f1.id
LIMIT 200;
```
"""


def build_prompt(user_query: str, location: dict) -> str:
    """Build the full prompt with schema + location context."""
    parts = [SCHEMA_CONTEXT]

    if location.get("lon"):
        lon, lat = location["lon"], location["lat"]
        r = location.get("radius_km", 5.0)
        dlat = location.get("delta_lat", r * 0.009)
        dlon = location.get("delta_lon", dlat)
        place = location.get("place", f"{lon},{lat}")

        parts.append(f"""
LOCATION CONTEXT (pre-resolved — use these numbers directly):
  Place  : {place}
  Centre : lon = {lon}, lat = {lat}
  Radius : {r} km
  BBox expansion (copy-paste into WHERE):
    m.bbox_maxx >= {lon - dlon:.6f}
    AND m.bbox_minx <= {lon + dlon:.6f}
    AND m.bbox_maxy >= {lat - dlat:.6f}
    AND m.bbox_miny <= {lat + dlat:.6f}
""")

    parts.append(f"USER QUERY: {user_query}")
    parts.append(f"\nGenerate one SQLite SELECT. End with LIMIT {SAFE_ROW_LIMIT}.")
    return "\n".join(parts)


def run(user_query: str, location: dict, llm) -> str:
    """Generate SQL via the LLM. Returns extracted SQL string."""
    prompt = build_prompt(user_query, location)
    raw = llm.generate(prompt, system=SYSTEM)
    return extract_sql(raw)


def extract_sql(text: str) -> str:
    """Pull first SQL statement from LLM output."""
    m = re.search(r'```sql\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r'(SELECT\s+.*?)(?:;|\Z)', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()
