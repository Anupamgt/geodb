# GeoDB Codebase Report

This document provides a detailed overview of the `gdb` (GeoDB) codebase located at `/Users/rakeshkumar/Downloads/gdb`.

## Overview
GeoDB is a local, sharded, spatially-aware database designed to manage and search geospatial files (such as `.tif`, `.kml`, and `.kmz`), combined with an AI-driven transformation pipeline. It leverages SQLite/SpatiaLite for storage and spatial indexing, and integrates an AI agent sandbox that writes, executes, and verifies python transformation scripts. It also provides a FastAPI-based web interface to interact with the database and run these pipelines.

## Key Components

The codebase is logically divided into several modules:

### 1. Database & Catalog (`geodb/db/`, `geodb/catalog/`, `geodb/schema.py`)
This subsystem handles the storage, indexing, and retrieval of metadata and geospatial bounding boxes for ingested files.
- **Sharded Architecture**: To maintain performance, the database is split by year into "shards" (e.g., `shard_2026.db`).
- **Catalog (`catalog/`)**: A master index (`catalog.db`) tracks which files exist in which shards. It maintains its own R-Tree and FTS5 indexes to route queries to the correct year shards without opening all of them.
- **Storage (`db/`)**: The `writer.py` handles inserting files and metadata into the catalog and shards. The `reader.py` provides querying capabilities:
  - **Spatial Search**: Uses SpatiaLite R-Tree indexes to query bounding boxes (`search_spatial`).
  - **Text Search**: Uses SQLite FTS5 for ranked full-text searches over filenames, descriptions, tags, and layers.
  - **Filter Search**: Dynamic queries based on CRS, resolution, bands, geometry types, and temporal data.

### 2. Ingestion (`geodb/ingest/`)
Handles the parsing and hashing of raw files into standardized metadata dictionary structures before they are inserted into the database.
- **`router.py`**: Identifies file types and routes them to the appropriate parser, computing SHA256 hashes and extracting binary blobs if small enough.
- **`kml_parser.py` & `tif_parser.py`**: Extract bounding boxes, coordinate reference systems (CRS), band counts, geometry types, and custom properties from KML/KMZ and TIFF files using libraries like `rasterio` and `fiona` (or `xml.etree`).

### 3. Agent Factory & Sandbox (`geodb/agent_factory/`)
Provides a secure environment to automatically generate and execute python code using Large Language Models (LLMs).
- **LLM Client**: Interfaces with LLMs using an OpenAI-compatible API. Originally designed around local Ollama models (`localhost:11434`), it has been modified to support the **Gemini API**.
- **Sandbox (`sandbox.py`)**: Runs agent-generated Python code in isolated subprocesses. It mounts temporary directories for input and output, restricts imports to prevent malicious actions, and captures stdout/stderr for the agent to review.
- **Executor**: Drives the multi-step agent loop (Plan $\rightarrow$ Code $\rightarrow$ Test $\rightarrow$ Verify). The agent recursively attempts to satisfy a prompt by writing code, testing it in the sandbox, and fixing errors until success.

### 4. Transformation Pipeline (`geodb/transform/`)
Builds on top of the Agent Factory specifically for geospatial processing tasks.
- Takes natural language requests (e.g., "Clip this raster to this KML boundary") and generates repeatable python scripts.
- **Templates**: Successful transformation scripts are saved as generic templates (using Jinja) that can be replayed on new data without needing the LLM again.

### 5. Web Interface (`geodb/web/`)
A graphical and programmatic frontend to the system.
- **FastAPI backend (`app.py`, `runner.py`)**: Exposes REST endpoints to ingest files, query the database, and kick off AI transformation jobs.
- Transformations and Agent tasks run in separate background threads, pushing progress updates via queues.

## Recent Modifications (Gemini Integration)
The codebase originally relied entirely on an OpenAI-compatible endpoint that defaulted to Ollama. It has been modified to seamlessly support the Gemini API:
- Added `"gemini"` as a CLI option in both the `agent_factory` and `transform` CLI modules.
- Updated the `LLMClient` initialization to dynamically route requests to `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` when the Gemini provider is selected, falling back to the `GEMINI_API_KEY` environment variable.
- Created `pyproject.toml` to package the app and expose the CLI tools globally. System-level dependencies (`gdal`, `spatialite-tools`) were installed via Homebrew to resolve complex build requirements for `rasterio` and `fiona`.
