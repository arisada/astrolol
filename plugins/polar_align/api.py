"""FastAPI router for the polar-alignment wizard (Part 2). Part 1's reticle view has no
routes yet -- its math and UI are still unbuilt, see SPEC.md."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request

from plugins.polar_align.wizard import WizardEngine, WizardRequest, WizardRun

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/polar_align", tags=["polar_align"])


def _engine(request: Request) -> WizardEngine:
    return request.app.state.polar_align_engine  # type: ignore[no-any-return]


@router.post("/wizard", status_code=201, response_model=WizardRun)
async def start_wizard(body: WizardRequest, request: Request) -> WizardRun:
    """Start a polar-alignment wizard run. 409 if one is already in progress."""
    try:
        return await _engine(request).start(body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/wizard", response_model=WizardRun)
async def get_wizard(request: Request) -> WizardRun:
    """Return the current or most recent wizard run."""
    run = _engine(request).current_run
    if run is None:
        raise HTTPException(status_code=404, detail="No polar alignment run has been started")
    return run


@router.delete("/wizard", status_code=204)
async def cancel_wizard(request: Request) -> None:
    """Cancel the running wizard. No-op if already idle. Does not move the mount back --
    see wizard.py's module docstring on why re-slewing on cancel would be actively harmful
    once the user has started physically adjusting the mount."""
    await _engine(request).cancel()
