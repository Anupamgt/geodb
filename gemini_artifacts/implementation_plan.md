# Setup and Install `geodb` CLI with Gemini API Support

This plan outlines the steps to install dependencies, configure the environment, setup the CLIs for the `geodb` project, and integrate Gemini API support.

## User Review Required

> [!IMPORTANT]
> - **Gemini API Integration**: We are modifying the codebase's LLM clients (`geodb/transform/llm_client.py` and `geodb/agent_factory/llm_client.py`) to support `"gemini"` as a first-class provider. It will connect to Gemini's OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai`).
> - **System Dependencies**: We are installing GDAL and SpatiaLite using Homebrew (`brew install gdal spatialite-tools`).

## Proposed Changes

### LLM Client & Config Changes

#### [MODIFY] [cli.py](file:///Users/rakeshkumar/Downloads/gdb/geodb/transform/cli.py)
Update the `--provider` argument choices to include `"gemini"`. When `--provider gemini` is selected, default the model to `"gemini-2.5-flash"`.

#### [MODIFY] [llm_client.py](file:///Users/rakeshkumar/Downloads/gdb/geodb/transform/llm_client.py)
In `_call_openai()`, if the provider is `gemini`, default the base URL to `https://generativelanguage.googleapis.com/v1beta/openai`.

#### [MODIFY] [llm_client.py](file:///Users/rakeshkumar/Downloads/gdb/geodb/geodb/agent_factory/llm_client.py)
In `_openai()`, if the provider is `gemini`, default the base URL to `https://generativelanguage.googleapis.com/v1beta/openai`.

### Configuration files

#### [NEW] [pyproject.toml](file:///Users/rakeshkumar/Downloads/gdb/pyproject.toml)
Create a standard `pyproject.toml` file to package `geodb` as a local python package and register entrypoints.

```toml
[build-system]
requires = ["setuptools>=61.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "geodb"
version = "0.1.0"
description = "Geospatial database and agentic transformation tool"
readme = "README.md"
authors = [
    { name = "Rakesh Kumar" }
]
classifiers = [
    "Programming Language :: Python :: 3",
]
dependencies = [
    "click",
    "tabulate",
    "fastapi",
    "uvicorn",
    "pydantic",
    "python-multipart",
    "requests",
    "lxml",
    "rasterio",
    "shapely",
    "geopandas",
    "fiona",
    "pyproj",
    "openpyxl",
    "xlsxwriter",
    "matplotlib",
]

[project.scripts]
geodb = "geodb.cli:cli"
geodb-transform = "geodb.transform.cli:main"
geodb-agent = "geodb.agent_factory.cli:main"
geodb-web = "geodb.web.__main__:main"
```

## Verification Plan

### Automated Tests
- Run `pip install -e .` from `/Users/rakeshkumar/Downloads/gdb`.
- Check if CLI commands are available:
  - `geodb --help`
  - `geodb-transform --help`
  - `geodb-agent --help`
  - `geodb-web --help`
- Run `geodb-transform config --provider gemini --api-key YOUR_GEMINI_API_KEY --model gemini-2.5-flash` to verify config storage.

### Manual Verification
- Test running `geodb stats` to confirm database connections.
- Run `geodb-web` to ensure the server starts correctly on port 8000.
