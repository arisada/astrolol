"""REST routes for the guide simulator: guiding controls, fault injection, settings."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from astrolol.core.guiding import (
    GuiderError,
    GuiderStatus,
    GuidingHealth,
    GuidingStats,
    SettleParams,
)
from astrolol.plugins.guide_simulator.settings import GuideSimSettings
from astrolol.plugins.guide_simulator.simulator import GuideSimulator, SimFaults

logger = structlog.get_logger()
router = APIRouter(prefix="/plugins/guide_simulator", tags=["guide_simulator"])


def _sim(request: Request) -> GuideSimulator:
    return request.app.state.guide_simulator  # type: ignore[no-any-return]


class SimReport(BaseModel):
    status: GuiderStatus
    health: GuidingHealth
    last_minute: GuidingStats
    faults: SimFaults


@router.get("/status", response_model=SimReport)
async def get_status(request: Request) -> SimReport:
    sim = _sim(request)
    now = sim.mark()
    return SimReport(
        status=sim.status(),
        health=sim.health(),
        last_minute=sim.stats(now - 60, now),
        faults=sim.faults(),
    )


@router.post("/connect", status_code=204)
async def connect(request: Request) -> None:
    _sim(request).connect()


@router.post("/disconnect", status_code=204)
async def disconnect(request: Request) -> None:
    await _sim(request).disconnect()


@router.post("/guide", status_code=204)
async def guide(request: Request, settle: SettleParams | None = None) -> None:
    """Start guiding; returns immediately (settling continues in the background)."""
    try:
        await _sim(request).guide(settle or SettleParams(), wait_settle=False)
    except GuiderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stop", status_code=204)
async def stop(request: Request) -> None:
    await _sim(request).stop()


class DitherBody(BaseModel):
    pixels: float = Field(default=3.0, gt=0)
    ra_only: bool = False
    settle: SettleParams = SettleParams()


@router.post("/dither", status_code=204)
async def dither(body: DitherBody, request: Request) -> None:
    """Dither and wait for settle."""
    try:
        await _sim(request).dither(body.pixels, body.ra_only, body.settle)
    except GuiderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ── Faults ────────────────────────────────────────────────────────────────────


class StarLossBody(BaseModel):
    duration_s: float | None = Field(default=30.0, gt=0, description="null = until cleared")


@router.post("/faults/star_loss", status_code=204)
async def star_loss(body: StarLossBody, request: Request) -> None:
    await _sim(request).lose_star(body.duration_s)


@router.post("/faults/stop_guiding", status_code=204)
async def stop_guiding_fault(request: Request) -> None:
    await _sim(request).stop_guiding_fault()


class SettleFailuresBody(BaseModel):
    count: int = Field(default=1, ge=0)


@router.post("/faults/settle_failures", status_code=204)
async def settle_failures(body: SettleFailuresBody, request: Request) -> None:
    _sim(request).fail_settles(body.count)


@router.post("/faults/clear", status_code=204)
async def clear_faults(request: Request) -> None:
    _sim(request).clear_faults()


# ── Settings ──────────────────────────────────────────────────────────────────


@router.get("/settings", response_model=GuideSimSettings)
async def get_settings(request: Request) -> GuideSimSettings:
    return _sim(request).settings


@router.put("/settings", response_model=GuideSimSettings)
async def put_settings(body: GuideSimSettings, request: Request) -> GuideSimSettings:
    """Applied immediately."""
    _sim(request).settings = body
    store = getattr(request.app.state, "profile_store", None)
    if store is not None:
        current = store.get_user_settings()
        updated = {**current.plugin_settings, "guide_simulator": body.model_dump()}
        store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    logger.info("guide_simulator.settings_updated")
    return body
