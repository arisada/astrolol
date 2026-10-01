"""FastAPI router for the polar-alignment wizard (Part 2) and the polar-scope reticle
view (Part 1). Part 1 has no device-connection requirement of its own -- site lat/lon and
the clock are all the GET route needs -- a mount is only consulted for the optional
axis_at_home check, see reticle.py's module docstring."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.equipment.optical_path import find_profile_site
from plugins.polar_align.reticle import ReticleCalibration, ReticleState, calibrate, compute_reticle_state
from plugins.polar_align.wizard import WizardEngine, WizardRequest, WizardRun

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/polar_align", tags=["polar_align"])

_PLUGIN_KEY = "polar_align"


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


async def _mount_ha_hours(request: Request, mount_id: str | None) -> float | None:
    """The mount's own reported Hour Angle right now, if a device id was given and it has
    one -- used only for the axis_at_home check, see reticle.py. None otherwise (not an
    error: the reticle still displays, just without that check)."""
    if mount_id is None:
        return None
    mm = getattr(request.app.state, "mount_manager", None)
    if mm is None:
        return None
    status = await mm.get_status(mount_id)
    return status.hour_angle


def _reticle_calibrations(request: Request) -> dict:
    raw = request.app.state.profile_store.get_user_settings().plugin_settings.get(_PLUGIN_KEY, {})
    return raw.get("reticle_calibrations", {})


def _save_reticle_calibration(request: Request, mount_node_id: str, calibration: ReticleCalibration) -> None:
    store = request.app.state.profile_store
    current = store.get_user_settings()
    plugin_block = dict(current.plugin_settings.get(_PLUGIN_KEY, {}))
    calibrations = dict(plugin_block.get("reticle_calibrations", {}))
    calibrations[mount_node_id] = calibration.model_dump(mode="json")
    plugin_block["reticle_calibrations"] = calibrations
    updated = {**current.plugin_settings, _PLUGIN_KEY: plugin_block}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))


def _clear_reticle_calibration(request: Request, mount_node_id: str) -> None:
    store = request.app.state.profile_store
    current = store.get_user_settings()
    plugin_block = dict(current.plugin_settings.get(_PLUGIN_KEY, {}))
    calibrations = dict(plugin_block.get("reticle_calibrations", {}))
    calibrations.pop(mount_node_id, None)
    plugin_block["reticle_calibrations"] = calibrations
    updated = {**current.plugin_settings, _PLUGIN_KEY: plugin_block}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))


class CalibrateReticleRequest(BaseModel):
    mount_node_id: str
    mount_id: str | None = None  # connected device id, for home_ha_hours; optional


@router.get("/reticle", response_model=ReticleState)
async def get_reticle(request: Request, mount_node_id: str | None = None, mount_id: str | None = None) -> ReticleState:
    """The current reticle reading. mount_node_id selects which saved calibration to
    apply (omit it, or pass one that's never been calibrated, to see the raw sky angle).
    mount_id is a separate, optional connected-device id for the live axis_at_home check --
    independent of mount_node_id since a mount can be calibrated without being connected
    right now, or connected under a different device id than it had at calibration time."""
    latitude, longitude = _site_latitude_longitude(request)
    calibration = None
    if mount_node_id is not None:
        raw = _reticle_calibrations(request).get(mount_node_id)
        if raw is not None:
            calibration = ReticleCalibration(**raw)
    ha_hours = await _mount_ha_hours(request, mount_id)
    return compute_reticle_state(_now(), latitude, longitude, calibration, ha_hours)


@router.post("/reticle/calibrate", response_model=ReticleCalibration)
async def calibrate_reticle(body: CalibrateReticleRequest, request: Request) -> ReticleCalibration:
    """Call at the instant the RA axis has been rotated by hand until the reticle's 0deg
    mark is plumb-vertical (SPEC.md section 2, "Calibration"). Persists the result keyed
    by mount_node_id, replacing any previous calibration for that mount node."""
    latitude, longitude = _site_latitude_longitude(request)
    ha_hours = await _mount_ha_hours(request, body.mount_id)
    calibration = calibrate(_now(), latitude, longitude, ha_hours)
    _save_reticle_calibration(request, body.mount_node_id, calibration)
    return calibration


@router.delete("/reticle/calibration/{mount_node_id}", status_code=204)
async def delete_reticle_calibration(mount_node_id: str, request: Request) -> None:
    """Clear a saved calibration. No-op if that mount node was never calibrated."""
    _clear_reticle_calibration(request, mount_node_id)


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
