"""FastAPI router for the autofocus plugin."""
from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from plugins.autofocus.engine import AutofocusEngine
from plugins.autofocus.models import AutofocusConfig, AutofocusRun

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/autofocus", tags=["autofocus"])


def _engine(request: Request) -> AutofocusEngine:
    return request.app.state.autofocus_engine  # type: ignore[no-any-return]


@router.post("/start", status_code=201, response_model=AutofocusRun)
async def start_autofocus(config: AutofocusConfig, request: Request) -> AutofocusRun:
    """Start an autofocus run. Returns 409 if a run is already in progress."""
    try:
        return await _engine(request).start(config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/abort", status_code=204)
async def abort_autofocus(request: Request) -> None:
    """Abort the running autofocus sequence. No-op if already idle."""
    await _engine(request).abort()


@router.get("/run", response_model=AutofocusRun)
async def get_run(request: Request) -> AutofocusRun:
    """Return the current or most recent autofocus run."""
    run = _engine(request).current_run
    if run is None:
        raise HTTPException(status_code=404, detail="No autofocus run has been started")
    return run


@router.get("/run/preview/{step}")
async def get_step_preview(step: int, request: Request) -> FileResponse:
    """Return the JPEG preview for a specific step (1-indexed)."""
    engine = _engine(request)
    run = engine.current_run
    if run is None:
        raise HTTPException(status_code=404, detail="No autofocus run found")
    if step < 1 or step > run.total_steps:
        raise HTTPException(status_code=400, detail=f"Step must be between 1 and {run.total_steps}")
    preview = engine.preview_path(step)
    if preview is None:
        raise HTTPException(status_code=404, detail=f"Preview for step {step} not yet available")
    path = Path(preview)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Preview file missing for step {step}")
    media_type = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/fits"
    return FileResponse(str(path), media_type=media_type)
