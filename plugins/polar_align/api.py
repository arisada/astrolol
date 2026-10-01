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


@router.post("/wizard/recheck", response_model=WizardRun)
async def recheck_wizard(request: Request) -> WizardRun:
    """One CONVERGING-phase reading: re-solve once and report how far the alt/az knobs
    have moved the axis since the fixed reference. 404 if no run has been started; 422 if
    the run isn't in the converging phase or the reading itself was bad (a solve failure,
    or an ambiguous/ill-conditioned geometry -- see solver.update_pole_offset) -- neither
    is fatal to the run, the caller can just try again."""
    try:
        return await _engine(request).recheck()
    except ValueError as exc:
        raise HTTPException(status_code=404 if "No polar" in str(exc) else 422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/wizard", status_code=204)
async def cancel_wizard(request: Request) -> None:
    """Stop the wizard. During CONVERGING this marks the run completed (the user is
    satisfied, nothing failed); otherwise it aborts the in-progress run. No-op if already
    idle. Does not move the mount back -- see wizard.py's module docstring on why
    re-slewing on cancel would be actively harmful once the user has started physically
    adjusting the mount."""
    await _engine(request).cancel()
