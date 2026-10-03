"""FastAPI router for the polar-alignment wizard (Part 2) and the polar-scope reticle
view (Part 1). Part 1 has no device-connection requirement at all -- site lat/lon and
the clock are all the GET route needs."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from astrolol.equipment.optical_path import find_profile_site
from plugins.polar_align.reticle import ReticleState, compute_reticle_state
from plugins.polar_align.wizard import (
    MAX_AUTO_REFRESH_INTERVAL_S,
    MIN_AUTO_REFRESH_INTERVAL_S,
    WizardEngine,
    WizardRequest,
    WizardRun,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/polar_align", tags=["polar_align"])


def _engine(request: Request) -> WizardEngine:
    return request.app.state.polar_align_engine  # type: ignore[no-any-return]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _site_latitude_longitude(request: Request) -> tuple[float, float]:
    app = request.app
    profile = getattr(app.state, "active_profile", None)
    equipment_store = getattr(app.state, "equipment_store", None)
    site = find_profile_site(profile, equipment_store) if profile is not None and equipment_store is not None else None
    if site is None:
        raise HTTPException(status_code=404, detail="No site location configured for the active profile")
    if site.latitude < 0:
        raise HTTPException(
            status_code=422,
            detail="The polar scope reticle view is northern-hemisphere only (SPEC.md section 6)",
        )
    return site.latitude, site.longitude


@router.get("/reticle", response_model=ReticleState)
async def get_reticle(request: Request) -> ReticleState:
    """The current reticle reading: where Polaris should sit on the dial right now,
    computed purely from the active profile's site location and the system clock."""
    latitude, longitude = _site_latitude_longitude(request)
    return compute_reticle_state(_now(), latitude, longitude)


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


class AutoRefreshRequest(BaseModel):
    interval_s: float = Field(ge=MIN_AUTO_REFRESH_INTERVAL_S, le=MAX_AUTO_REFRESH_INTERVAL_S)


@router.post("/wizard/auto_refresh", response_model=WizardRun)
async def start_auto_refresh(body: AutoRefreshRequest, request: Request) -> WizardRun:
    """Start (or re-time) periodic automatic rechecks during CONVERGING. 404 if no run
    has been started; 422 if it isn't in the converging phase yet."""
    try:
        return await _engine(request).start_auto_refresh(body.interval_s)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "No polar" in str(exc) else 422, detail=str(exc)) from exc


@router.delete("/wizard/auto_refresh", status_code=204)
async def stop_auto_refresh(request: Request) -> None:
    """Stop periodic automatic rechecks. No-op if it wasn't running."""
    try:
        await _engine(request).stop_auto_refresh()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/wizard", status_code=204)
async def cancel_wizard(request: Request) -> None:
    """Stop the wizard. During CONVERGING this marks the run completed (the user is
    satisfied, nothing failed); otherwise it aborts the in-progress run. No-op if already
    idle. Does not move the mount back -- see wizard.py's module docstring on why
    re-slewing on cancel would be actively harmful once the user has started physically
    adjusting the mount."""
    await _engine(request).cancel()
