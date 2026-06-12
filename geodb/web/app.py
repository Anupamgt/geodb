"""
GeoFlow Web API — FastAPI backend.

Start:  python -m geodb.web
"""
import asyncio
import json
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Allow uploads up to 10 GB
try:
    import multipart.multipart as _mp
    _mp.MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024
except Exception:
    pass

import geodb.agent_factory.config as af_cfg
from geodb.agent_factory.llm_client import LLMClient
from geodb.agent_factory.storage import agent_store
from geodb.web.runner import PipelineSession, run_pipeline_create, run_pipeline_saved

app = FastAPI(title="GeoFlow", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = Path(af_cfg.DATA_DIR) / ".uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_sessions: dict[str, PipelineSession] = {}

GEO_EXT = {".kml", ".kmz", ".geojson", ".tif", ".tiff", ".shp",
           ".gpx", ".csv", ".xlsx", ".xls", ".json", ".zip", ".gdb"}


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── Agents ────────────────────────────────────────────────────────────────────

@app.get("/api/agents")
async def list_agents():
    return agent_store.list_agents()


@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str):
    try:
        return agent_store.load(agent_id).to_dict()
    except FileNotFoundError:
        raise HTTPException(404, "Agent not found")


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if agent_store.delete(agent_id):
        return {"ok": True}
    raise HTTPException(404, "Agent not found")


# ── File upload ───────────────────────────────────────────────────────────────

@app.post("/api/files/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    saved = []
    for f in files:
        dst = UPLOAD_DIR / f.filename
        content = await f.read()
        dst.write_bytes(content)
        saved.append({"name": f.filename, "path": str(dst), "size": len(content)})
    return saved


# ── File search / browse ──────────────────────────────────────────────────────

@app.get("/api/files/search")
async def search_files(q: str = "", path: str = ""):
    base = path or af_cfg.PROJECT_DIR
    results = []
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs
                       if not d.startswith(".") and d not in ("__pycache__", "node_modules")]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in GEO_EXT:
                    continue
                if q and q.lower() not in fname.lower():
                    continue
                fp = os.path.join(root, fname)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    continue
                results.append({
                    "name": fname,
                    "path": fp,
                    "size": size,
                    "ext": ext.lstrip("."),
                    "rel": os.path.relpath(fp, af_cfg.PROJECT_DIR),
                })
                if len(results) >= 300:
                    break
            if len(results) >= 300:
                break
    except Exception:
        pass
    return results


@app.get("/api/files/dirs")
async def list_dirs(path: str = ""):
    base = path or af_cfg.PROJECT_DIR
    try:
        parent = str(Path(base).parent)
        dirs = []
        for name in sorted(os.listdir(base)):
            fp = os.path.join(base, name)
            if os.path.isdir(fp) and not name.startswith("."):
                dirs.append({"name": name, "path": fp})
        return {"path": base, "dirs": dirs, "parent": parent}
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Pipeline ──────────────────────────────────────────────────────────────────

class CreateReq(BaseModel):
    task: str
    file_paths: list[str]
    output_dir: Optional[str] = None


class RunReq(BaseModel):
    agent_id: str
    file_paths: list[str]
    output_dir: Optional[str] = None
    params: Optional[dict] = None


def _new_session() -> PipelineSession:
    sid = str(uuid.uuid4())[:8]
    s = PipelineSession(session_id=sid)
    _sessions[sid] = s
    return s


@app.post("/api/pipeline/create")
async def pipeline_create(req: CreateReq):
    s = _new_session()
    llm = LLMClient()
    t = threading.Thread(
        target=run_pipeline_create,
        args=(s, req.task, req.file_paths, llm, req.output_dir),
        daemon=True,
    )
    t.start()
    s.thread = t
    return {"session_id": s.session_id}


@app.post("/api/pipeline/run")
async def pipeline_run(req: RunReq):
    s = _new_session()
    llm = LLMClient()
    t = threading.Thread(
        target=run_pipeline_saved,
        args=(s, req.agent_id, req.file_paths, llm, req.output_dir, req.params),
        daemon=True,
    )
    t.start()
    s.thread = t
    return {"session_id": s.session_id}


@app.get("/api/pipeline/{sid}/events")
async def pipeline_events(sid: str):
    if sid not in _sessions:
        raise HTTPException(404, "Session not found")
    session = _sessions[sid]

    async def stream():
        loop = asyncio.get_event_loop()
        while True:
            try:
                event = await loop.run_in_executor(
                    None, lambda: session.event_queue.get(timeout=1.0)
                )
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "aborted", "error"):
                    break
            except Exception:
                if session.status in ("done", "error"):
                    break
                yield f"data: {json.dumps({'type':'ping'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/pipeline/{sid}/decision")
async def pipeline_decision(sid: str, body: dict):
    if sid not in _sessions:
        raise HTTPException(404, "Session not found")
    _sessions[sid].decision_queue.put(body.get("action", "abort"))
    return {"ok": True}


# ── Output files ──────────────────────────────────────────────────────────────

@app.get("/api/output/files")
async def output_files():
    out = af_cfg.OUTPUT_DIR
    if not os.path.isdir(out):
        return []
    return [
        {"name": f, "size": os.path.getsize(os.path.join(out, f)),
         "ext": os.path.splitext(f)[1].lower().lstrip(".")}
        for f in sorted(os.listdir(out))
        if os.path.isfile(os.path.join(out, f))
    ]


@app.get("/api/output/download/{filename}")
async def download_file(filename: str):
    fp = os.path.join(af_cfg.OUTPUT_DIR, filename)
    if not os.path.isfile(fp):
        raise HTTPException(404)
    return FileResponse(fp, filename=filename)


# ── Map file viewer ───────────────────────────────────────────────────────────

@app.get("/api/mapfile")
async def serve_mapfile(path: str):
    if not os.path.isfile(path):
        raise HTTPException(404, "Map file not found")
    ext = os.path.splitext(path)[1].lower()
    media = "text/html" if ext == ".html" else "application/octet-stream"
    return FileResponse(path, media_type=media)
