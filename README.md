# GeoDB (`geodb`)

**Geospatial database, spatial search engine, and autonomous AI transformation pipeline.**

GeoDB is a local, sharded, spatially-aware SQLite/SpatiaLite database designed to store, search, and transform complex spatial datasets (`.tif`, `.kml`, `.kmz`, `.geojson`, `.shp`). It integrates an autonomous AI agent runtime (supporting **Google Gemini**, OpenAI, Anthropic, and local Ollama models) that generates, executes, and self-corrects Python transformation workflows in an isolated sandbox.

---

## Key Features

- **Sharded SQLite & SpatiaLite Storage**: Automatically partitions spatial files by year (`data/YYYY.db`) with central catalog routing (`data/catalog.db`).
- **High-Performance Search**: Combined R-Tree bounding-box spatial indexing (`search_spatial`) and FTS5 full-text keyword indexing across filenames, attributes, and tags.
- **Autonomous Agent Factory**: Generates custom Python workflows (`geopandas`, `rasterio`, `shapely`) to execute grid sampling, raster clipping, coordinate extraction, and contour mapping.
- **Modern Web Interface**: Responsive single-page dashboard built with FastAPI and styled in a flat VS Code dark aesthetic (`#1e1e1e`), featuring real-time token tracking and step progression monitoring.
- **Multi-Cloud & Serverless Ready**: Dynamic model provider switching with Vercel deployment support and `/tmp` ephemeral fallback handling.

---

## Installation & Quickstart

### Prerequisite System Dependencies
Ensure GDAL and SpatiaLite tools are installed on your host OS:
```bash
# macOS (Homebrew)
brew install gdal spatialite-tools
```

### Python Virtual Environment Setup
```bash
git clone https://github.com/your-org/geodb.git
cd geodb

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

---

## Usage

### 1. Web Dashboard
Launch the FastAPI web server locally:
```bash
geodb-web
# Or: python -m geodb.web
```
Open your browser to `http://localhost:8000`. API interactive documentation is available at `http://localhost:8000/docs`.

### 2. Command Line Interface (CLI)
Ingest spatial files into the sharded database:
```bash
geodb ingest ./sample_data/
```
Search spatial datasets across shards:
```bash
geodb search --text "elevation" --type tif
```
Run an agentic transformation workflow directly from the terminal:
```bash
geodb-transform run --files sample_area.kml --model gemini
```

---

## API Endpoints Overview

| Method | Route | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Service liveness and health check |
| `GET` | `/api/status` | Live LLM token consumption metrics (`tokens_used` / `tokens_limit`) |
| `POST` | `/api/files/upload` | Upload geospatial files into active storage |
| `GET` | `/api/files/search` | Query catalog across spatial R-Tree and FTS5 indexes |
| `POST` | `/api/pipeline/create` | Initialize an autonomous transformation plan |
| `GET` | `/api/pipeline/{sid}/events` | Real-time Server-Sent Events (SSE) execution stream |

---

## License
MIT License.
