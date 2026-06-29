# Product Requirements Document & Progress Report: GeoDB (gdb)

## Executive Summary & System Architecture

GeoDB (`geodb`) is a local, sharded, spatially-aware database and autonomous transformation engine engineered to manage, query, and transform complex geospatial files (such as raster `.tif` and vector `.kml`/`.kmz` datasets). Designed for geospatial engineers, GIS analysts, and automated data pipelines, the platform combines a SQLite/SpatiaLite storage core with a multi-cloud AI agent runtime capable of writing, executing, and validating custom Python spatial processing workflows in an isolated sandbox. By coupling spatial indexing (R-Tree) and full-text keyword search (FTS5) with an LLM-driven execution loop, GeoDB eliminates manual GIS scripting while maintaining strict local persistence and reproducibility.

### Architectural Highlights
- **Storage & Sharding Core**: Employs a sharded SQLite architecture partitioned by year (`data/YYYY.db`) managed via `geodb/config.py` and `geodb/db/`. A central master catalog (`data/catalog.db`) utilizes SQLite FTS5 for full-text search across filenames and layer descriptions, and SpatiaLite R-Tree spatial indexes for fast bounding-box queries (`search_spatial`), routing queries to target year shards without opening unneeded databases.
- **Geospatial Ingestion Pipeline**: Driven by `geodb/ingest/router.py`, the ingestion system computes SHA-256 binary hashes for deduplication and extracts metadata such as CRS, resolution, band counts, and geometries using `kml_parser.py` (via `lxml` and `shapely`) and `tif_parser.py` (via `rasterio`). Small files (under 500 MB by default) have their binary blobs persisted directly inside SQLite WAL-mode tables.
- **Autonomous Agent Factory & Code Sandbox**: Located in `geodb/agent_factory/`, this runtime constructs multi-step transformation plans (`creation/step_planner.py`), generates Python code (`creation/step_coder.py`), and executes scripts within isolated subprocesses (`runtime/sandbox.py`). The sandbox mounts dedicated input/output directories and enforces strict execution limits, capturing stderr/stdout to feed back into an iterative LLM self-correction loop (`runtime/agent_runner.py`).
- **Web Interface & REST Backend**: Built on FastAPI (`geodb/web/app.py`), serving a responsive single-page web interface (`geodb/web/static/index.html`) styled with a modern VS Code dark theme (`#1e1e1e`). Long-running agent jobs and pipeline executions are decoupled from HTTP request threads using asynchronous queue bridging (`geodb/web/runner.py`), streaming live execution events and token consumption metrics (`/api/status`) to the frontend.
- **Multi-Cloud LLM Abstraction Layer**: Implemented in `geodb/agent_factory/llm_client.py` and `geodb/transform/llm_client.py`, supporting dynamic switching across cloud providers (Google Gemini via `generativelanguage.googleapis.com`, OpenAI, and Anthropic) as well as local Ollama instances (`localhost:11434`), complete with global token consumption tracking.

---

## Completed Milestones (What Has Been Done)

### Phase 1: Database Foundation & Spatial Catalog ✅ [100% Completed]
- Implemented core schema generation in `geodb/schema.py`, defining SpatiaLite geometry columns, R-Tree spatial tables, and FTS5 virtual tables.
- Built database connection pooling and SQLite PRAGMA configuration (WAL mode, 256MB mmap, memory temp store) in `geodb/db/connection.py`.
- Created shard routing logic (`ShardManager`) and read/write access patterns in `geodb/db/writer.py` and `geodb/db/reader.py`.
- Developed CLI database administration commands (`ingest`, `search`, `export`, `stats`, `list-tags`) in `geodb/cli.py`.

### Phase 2: Geospatial Ingestion Engine & File Parsing ✅ [100% Completed]
- Created ingestion routing and streaming SHA-256 hashing in `geodb/ingest/router.py`, enforcing file size thresholds (`MAX_BLOB_BYTES`).
- Implemented KML/KMZ parsing in `geodb/ingest/kml_parser.py` using `lxml` to extract bounding boxes, 2D/3D coordinate tuples, placemark counts, and layer styles.
- Implemented GeoTIFF raster extraction in `geodb/ingest/tif_parser.py` using `rasterio` to capture affine transformation matrices, CRS epsg codes, pixel resolutions, and sensor tags.

### Phase 3: Autonomous Agent Factory & Code Sandbox ✅ [100% Completed]
- Built the multi-step agent prompt generation and code synthesis pipeline across `geodb/agent_factory/creation/agent_creator.py`, `step_planner.py`, and `step_coder.py`.
- Implemented isolated subprocess code execution and error capturing in `geodb/agent_factory/runtime/sandbox.py` and `step_runner.py`.
- Added domain-specific knowledge pattern injection (`geodb/agent_factory/knowledge/loader.py`), providing the LLM with pre-validated patterns for `geopandas`, `rasterio`, `openpyxl`, and shapefile writing.
- Constructed persistent JSON-based agent definition storage in `geodb/agent_factory/storage/agent_store.py`.

### Phase 4: Agentic Transformation Pipeline & Replay Engine ✅ [100% Completed]
- Developed the natural language transformation orchestrator in `geodb/transform/pipeline/orchestrator.py` and runner in `runner.py`.
- Implemented template persistence in `geodb/transform/storage/template.py`, allowing successful AI-generated transformation scripts to be saved as parameterized JSON recipes (`geodb/transform/examples/*.json`).
- Exposed transformation workflows via dedicated CLI commands (`run`, `replay`, `list-templates`, `config`) in `geodb/transform/cli.py`.

### Phase 5: Web Application Backend & Frontend UI ✅ [100% Completed]
- Engineered REST endpoints in `geodb/web/app.py` for file uploads (`/api/files/upload`), cross-shard search (`/api/files/search`), agent management (`/api/agents`), and pipeline execution (`/api/pipeline/create`).
- Designed thread-safe queue bridging (`PipelineSession`) in `geodb/web/runner.py` to allow non-blocking user decisions (`/api/pipeline/{sid}/decision`) and real-time event polling (`/api/pipeline/{sid}/events`).
- Built a clean single-page UI in `geodb/web/static/index.html` featuring a flat VS Code dark aesthetic, visual step progression tracking, and an interactive file browser.

### Phase 6: Multi-Cloud LLM Integration & Serverless Hardening ✅ [100% Completed]
- Integrated global token consumption tracking (`tokens_used`, `tokens_limit`) across `llm_client.py` modules, exposing real-time usage via `GET /api/status`.
- Added dynamic provider routing for Google Gemini API (`GEMINI_API_KEY`), OpenAI, Anthropic, and Ollama inside `geodb/agent_factory/llm_client.py`.
- Hardened codebase for serverless deployment (Vercel) by creating `requirements.txt`, mapping ephemeral write operations to `/tmp`, and configuring Vercel entrypoints in `pyproject.toml`.

### Phase 7: Natural Language Search Query REPL 🟡 [In Progress / Initialized]
- Created core REPL structure and natural language query parser in `geodb/nl_search/cli.py` and `geodb/nl_search/pipeline.py`.
- Implemented SQL generation translation layers in `geodb/nl_search/executor.py` and `location.py`.
- *Note*: Currently operates as a standalone script; entry points are not yet wired into global console scripts or the REST backend.

---

## Current System Capabilities Matrix

| Module | Route/Entry Point | Access Persona | Data Source | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Database & Catalog** | `geodb ingest`, `geodb search`, `geodb export`, `geodb stats` (CLI) | Data Engineer / CLI User | Local spatial files (`.kml`, `.tif`), SQLite shards (`data/*.db`) | 🟢 Live |
| **Web Interface & API** | `geodb-web`, `GET /`, `POST /api/files/upload`, `GET /api/files/search` | GIS Analyst / Web User | Filesystem (`DATA_DIR`), SQLite shards, LLM APIs | 🟢 Live |
| **Agent Factory Runtime** | `POST /api/pipeline/create`, `geodb/agent_factory/cli.py` | Automated Agent / Web Backend | Knowledge markdown files, LLM APIs, Subprocess Sandbox | 🟢 Live |
| **Transformation Pipeline** | `geodb-transform run`, `geodb-transform replay` (CLI) | Data Engineer / CLI User | Saved JSON templates (`transform/examples/*.json`), Local files | 🟢 Live |
| **LLM & Token Tracker** | `GET /api/status`, internal `LLMClient` instances | System Admin / Frontend UI | Cloud LLM HTTP APIs (Gemini/OpenAI), Local Ollama | 🟢 Live |
| **Natural Language Search** | `python -m geodb.nl_search.cli` (Module CLI) | CLI User | SQLite Catalog & Shards, LLM APIs | 🟡 Partial |

---

## Future Roadmap & Next Horizons (What Needs To Be Done)

### Phase 8: Comprehensive Automated Test Suite & CI/CD Pipeline
- **Objective**: Establish production-grade code reliability and regression prevention across spatial parsing, shard routing, and agent sandboxing.
- **Tasks Remaining**:
  - Implement unit tests for spatial catalog operations (`geodb/db/reader.py` and `writer.py`), verifying R-Tree bounding box intersection accuracy.
  - Create integration tests for `kml_parser.py` and `tif_parser.py` using synthetic fixtures to validate CRS extraction and SHA-256 hashing.
  - Build mock LLM responses to test multi-step agent self-correction loops in `geodb/agent_factory/runtime/agent_runner.py` without incurring API costs.

### Phase 9: Expanded Ingestion Format Support (Vector & Raster)
- **Objective**: Eliminate format bottlenecks by extending the database ingestion engine beyond KML and GeoTIFF to support industry-standard spatial formats.
- **Tasks Remaining**:
  - Update `geodb/config.py` (`SUPPORTED_EXTENSIONS`) and `geodb/ingest/router.py` to register `.geojson`, `.shp`, `.gpkg` (GeoPackage), and `.nc` (NetCDF).
  - Implement `geodb/ingest/vector_parser.py` utilizing `geopandas`/`fiona` to extract multi-layer bounding boxes and attribute schemas for Shapefiles and GeoPackages.
  - Implement `geodb/ingest/netcdf_parser.py` utilizing `xarray`/`netCDF4` to extract multidimensional bounding coordinates and temporal slices.

### Phase 10: Natural Language Search Integration & Web UI Wiring
- **Objective**: Empower web users to perform complex geospatial queries using plain English directly from the web dashboard.
- **Tasks Remaining**:
  - Register `geodb-nl-search = "geodb.nl_search.cli:main"` in `pyproject.toml` under `[project.scripts]`.
  - Expose natural language search capabilities via a new REST endpoint: `POST /api/search/nl` in `geodb/web/app.py`.
  - Add a dedicated search mode toggle on the web frontend (`geodb/web/static/index.html`) to display LLM-generated SQL explanations alongside tabular results.

### Phase 11: Containerized Agent Sandbox & Security Hardening
- **Objective**: Protect host infrastructure from arbitrary code execution during LLM code generation by upgrading the subprocess sandbox to containerized isolation.
- **Tasks Remaining**:
  - Refactor `geodb/agent_factory/runtime/sandbox.py` to optionally execute step scripts inside ephemeral Docker containers or Apple Virtualization framework microVMs.
  - Enforce strict CPU time limits, memory quotas, and complete network isolation (disable outbound internet access) during code transformation runs.
  - Implement automated static code analysis (AST scanning) prior to script execution to block disallowed modules or system call attempts.

### Phase 12: Project Documentation & Onboarding Standardization
- **Objective**: Provide clear onboarding paths, developer setup guides, and API documentation for open-source contributors and enterprise adopters.
- **Tasks Remaining**:
  - Author the primary `README.md` file at the project root (currently missing despite being referenced in `pyproject.toml`), detailing system architecture, Homebrew dependency setup (`gdal`, `spatialite-tools`), and CLI quickstart commands.
  - Generate Swagger/OpenAPI annotations across all REST routes in `geodb/web/app.py` for automated interactive API documentation.
