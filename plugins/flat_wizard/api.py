"""FastAPI router for the flat calibration wizard plugin."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request

from plugins.flat_wizard.engine import FlatWizardEngine
from plugins.flat_wizard.models import FlatWizardConfig, FlatWizardRun

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/flat_wizard", tags=["flat_wizard"])


def _engine(request: Request) -> FlatWizardEngine:
    return request.app.state.flat_wizard_engine  # type: ignore[no-any-return]


@router.post("/start", status_code=201, response_model=FlatWizardRun)
async def start_run(config: FlatWizardConfig, request: Request) -> FlatWizardRun:
    """Start a flat-wizard run. Returns 409 if a run is already in progress."""
    try:
        return await _engine(request).start(config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/abort", status_code=204)
async def abort_run(request: Request) -> None:
    """Abort the running flat wizard. No-op if already idle."""
    await _engine(request).abort()


@router.get("/run", response_model=FlatWizardRun)
async def get_run(request: Request) -> FlatWizardRun:
    """Return the current or most recent flat-wizard run."""
    run = _engine(request).current_run
    if run is None:
        raise HTTPException(status_code=404, detail="No flat wizard run has been started")
    return run
