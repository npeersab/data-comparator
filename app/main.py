"""FastAPI app: serves the frontend and exposes the SSE comparison endpoint."""

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .compare import compare_events
from .connections import (
    SavedConnection,
    list_connections,
    get_connection,
    upsert_connection,
    update_connection,
    delete_connection,
    to_public,
    to_full,
    to_config,
)
from .db import SUPPORTED_DIALECTS
from .schemas import (
    CompareRequest,
    SavedCompareRequest,
    SavedConnectionIn,
    SavedConnectionOut,
    SavedConnectionFull,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

app = FastAPI(title="Data Comparator", version="1.1.0")


@app.get("/", response_class=FileResponse)
async def index():
    return os.path.join(STATIC_DIR, "index.html")


@app.get("/admin", response_class=FileResponse)
async def admin():
    return os.path.join(STATIC_DIR, "admin.html")


@app.get("/api/dialects")
async def dialects():
    return {"dialects": sorted(SUPPORTED_DIALECTS.keys())}


# ---- Saved connection presets ----


@app.get("/api/connections", response_model=list[SavedConnectionOut])
async def list_saved_connections():
    return [to_public(c) for c in list_connections()]


@app.get("/api/connections/{conn_id}", response_model=SavedConnectionFull)
async def get_saved_connection(conn_id: int):
    conn = get_connection(conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return to_full(conn)


@app.post("/api/connections", response_model=SavedConnectionOut, status_code=201)
async def save_connection(data: SavedConnectionIn):
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    return to_public(upsert_connection(data))


@app.put("/api/connections/{conn_id}", response_model=SavedConnectionOut)
async def update_saved_connection(conn_id: int, data: SavedConnectionIn):
    """Update a preset by id. The edit targets the row by id (not by name), so
    renaming a preset in place does not create a duplicate row."""
    try:
        conn = update_connection(conn_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return to_public(conn)


@app.delete("/api/connections/{conn_id}")
async def remove_saved_connection(conn_id: int):
    if not delete_connection(conn_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"ok": True}


@app.post("/api/compare/stream")
async def compare_stream(req: CompareRequest):
    def event_gen():
        yield from compare_events(
            req.source, req.target, req.max_mismatch_size
        )

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable proxy buffering so events reach the client promptly.
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/compare/saved")
async def compare_saved(req: SavedCompareRequest):
    """Compare two saved connections by id. Credentials stay server-side."""

    def _resolve(conn_id: int) -> SavedConnection:
        conn = get_connection(conn_id)
        if conn is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        return conn

    # Resolve (and 404) before the streaming response starts, so a missing id
    # is reported as a real 404 rather than an error mid-stream. The SQL query
    # for each side is supplied at run time, not stored with the preset.
    source_cfg = to_config(_resolve(req.source_id), req.source_query)
    target_cfg = to_config(_resolve(req.target_id), req.target_query)

    def event_gen():
        yield from compare_events(source_cfg, target_cfg, req.max_mismatch_size)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Serve static assets (index.html is served separately above).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
