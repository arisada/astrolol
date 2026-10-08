"""REST routes of the built-in guider."""

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
from plugins.guider.calibration import Calibration
from plugins.guider.darks import DarkInfo
from plugins.guider.guider import BuiltinGuider
from plugins.guider.settings import GuiderSettings

logger = structlog.get_logger()
router = APIRouter(prefix="/plugins/guider", tags=["guider"])


def _guider(request: Request) -> BuiltinGuider:
    return request.app.state.builtin_guider  # type: ignore[no-any-return]


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


class GuiderReport(BaseModel):
    status: GuiderStatus
    health: GuidingHealth
    last_minute: GuidingStats
    calibration: Calibration | None
    darks: list[DarkInfo]


@router.get("/status", response_model=GuiderReport)
async def get_status(request: Request) -> GuiderReport:
    g = _guider(request)
    now = g.mark()
    return GuiderReport(
        status=g.status(),
        health=g.health(),
        last_minute=g.stats(now - 60, now),
        calibration=g.calibration,
        darks=g.darks.describe(),
    )


class GuideBody(BaseModel):
    settle: SettleParams = SettleParams()
    recalibrate: bool = False


@router.post("/guide", status_code=204)
async def guide(request: Request, body: GuideBody | None = None) -> None:
    """Start guiding. Returns at once; progress arrives as guiding events."""
    body = body or GuideBody()
    g = _guider(request)
    try:
        await g.guide(body.settle, recalibrate=body.recalibrate, wait_settle=False)
    except GuiderError as exc:
        raise _conflict(exc) from exc


@router.post("/stop", status_code=204)
async def stop(request: Request) -> None:
    await _guider(request).stop()


@router.post("/pause", status_code=204)
async def pause(request: Request) -> None:
    await _guider(request).pause()


@router.post("/resume", status_code=204)
async def resume(request: Request) -> None:
    await _guider(request).resume()


class DitherBody(BaseModel):
    pixels: float = Field(default=3.0, gt=0)
    ra_only: bool = False
    settle: SettleParams = SettleParams()


@router.post("/dither", status_code=204)
async def dither(body: DitherBody, request: Request) -> None:
    """Dither and wait for the guider to settle."""
    try:
        await _guider(request).dither(body.pixels, body.ra_only, body.settle)
    except GuiderError as exc:
        raise _conflict(exc) from exc


@router.delete("/calibration", status_code=204)
async def clear_calibration(request: Request) -> None:
    """Forget the calibration: the next run calibrates again."""
    _guider(request).calibration = None


class DarkBody(BaseModel):
    count: int = Field(default=10, ge=1, le=50)


@router.post("/darks", response_model=DarkInfo)
async def capture_dark(body: DarkBody, request: Request) -> DarkInfo:
    """Take a dark with the scope covered. Returns when the frames are in."""
    g = _guider(request)
    try:
        dark = await g.capture_dark(body.count)
    except GuiderError as exc:
        raise _conflict(exc) from exc
    return next(d for d in g.darks.describe() if d.region == dark.region and d.exposure == dark.exposure)


@router.delete("/darks", status_code=204)
async def clear_darks(request: Request) -> None:
    _guider(request).darks.clear()


@router.get("/settings", response_model=GuiderSettings)
async def get_settings(request: Request) -> GuiderSettings:
    return _guider(request).settings


@router.put("/settings", response_model=GuiderSettings)
async def put_settings(body: GuiderSettings, request: Request) -> GuiderSettings:
    """Applied at the next run (a run in progress keeps its settings)."""
    g = _guider(request)
    if g.status().active and (body.exposure, body.gain) != (g.settings.exposure, g.settings.gain):
        raise _conflict(GuiderError("Stop guiding before changing the exposure or gain"))
    if body.exposure != g.settings.exposure or body.gain != g.settings.gain:
        g.calibration = None  # the star's response depends on the exposure the loop works at
    g.settings = body
    store = getattr(request.app.state, "profile_store", None)
    if store is not None:
        current = store.get_user_settings()
        updated = {**current.plugin_settings, "guider": body.model_dump()}
        store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    logger.info("guider.settings_updated")
    return body
