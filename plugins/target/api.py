"""FastAPI router for the target plugin."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

from astrolol.equipment.models import SiteItem
from plugins.target.ephemeris import compute_ephemeris
from plugins.target.models import EphemerisResult, TargetSettings

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/target", tags=["target"])

_PLUGIN_KEY = "target"


def _store(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.profile_store


def _get_settings(request: Request) -> TargetSettings:
    raw = _store(request).get_user_settings().plugin_settings.get(_PLUGIN_KEY, {})
    return TargetSettings(**raw)


def _save_settings(request: Request, settings: TargetSettings) -> None:
    store = _store(request)
    current = store.get_user_settings()
    # mode='json' ensures datetime fields (added_at) are serialised as ISO strings
    updated = {**current.plugin_settings, _PLUGIN_KEY: settings.model_dump(mode="json")}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))


def _resolve_site(request: Request) -> SiteItem | None:
    """Find the first SiteItem in the active profile's equipment tree."""
    store = _store(request)
    last_id = store.get_last_active_id()
    if not last_id:
        return None
    try:
        profile = store.get(last_id)
    except KeyError:
        return None
    equipment_store = getattr(request.app.state, "equipment_store", None)
    if equipment_store is None or not profile.roots:
        return None
    for node in profile.roots:
        try:
            item = equipment_store.get(node.item_id)
            if isinstance(item, SiteItem):
                return item
        except KeyError:
            pass
    return None


# ── Settings (includes favorites list) ────────────────────────────────────────

@router.get("/settings", response_model=TargetSettings)
async def get_settings(request: Request) -> TargetSettings:
    """Return persisted target plugin settings including favorites."""
    return _get_settings(request)


@router.put("/settings", response_model=TargetSettings)
async def put_settings(body: TargetSettings, request: Request) -> TargetSettings:
    """Persist target plugin settings (favorites, min altitude)."""
    _save_settings(request, body)
    logger.info("target.settings_saved", favorites_count=len(body.favorites))
    return body


# ── Ephemeris ──────────────────────────────────────────────────────────────────

@router.get("/ephemeris", response_model=EphemerisResult)
async def get_ephemeris(
    request: Request,
    ra: float = Query(..., ge=0.0, lt=360.0, description="ICRS RA in degrees"),
    dec: float = Query(..., ge=-90.0, le=90.0, description="ICRS Dec in degrees"),
    date: str | None = Query(None, description="Observation date ISO 8601 (defaults to today UTC)"),
) -> EphemerisResult:
    """Compute rise/set/transit, altitude curve, twilight, and moon data.

    Requires a SiteItem in the active profile's equipment tree.
    Returns observer_location_missing=true when no site is configured.
    """
    site = _resolve_site(request)
    if site is None:
        logger.warning("target.ephemeris_no_location")
        return EphemerisResult(observer_location_missing=True)

    # Parse optional date
    obs_date = None
    if date is not None:
        try:
            obs_date = datetime.fromisoformat(date).date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date; use ISO 8601.")

    settings = _get_settings(request)

    try:
        result = compute_ephemeris(
            ra_deg=ra,
            dec_deg=dec,
            latitude=site.latitude,
            longitude=site.longitude,
            altitude_m=site.altitude,
            obs_date=obs_date,
            min_altitude_deg=settings.min_altitude_deg,
        )
    except Exception as exc:
        logger.error("target.ephemeris_error", ra=ra, dec=dec, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="Ephemeris computation failed") from exc

    logger.info(
        "target.ephemeris_computed",
        ra=ra,
        dec=dec,
        circumpolar=result.circumpolar,
        never_rises=result.never_rises,
        peak_alt=result.peak_alt,
    )
    return result
