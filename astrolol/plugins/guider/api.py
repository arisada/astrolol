"""REST routes of the built-in guider."""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from astrolol.core.guiding import (
    GuiderError,
    GuiderStatus,
    GuidingHealth,
    GuidingStats,
    SettleParams,
)
from astrolol.plugins.guider.calibration import Calibration
from astrolol.plugins.guider.darks import DarkInfo
from astrolol.plugins.guider.guider import BuiltinGuider
from astrolol.plugins.guider.settings import GuiderSettings
from astrolol.plugins.guider.view import ViewInfo

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
    pixel_scale_source: Literal["settings", "optics"] | None = None  # where status.pixel_scale comes from


@router.get("/status", response_model=GuiderReport)
async def get_status(request: Request) -> GuiderReport:
    g = _guider(request)
    await g.refresh_pixel_scale(max_age=10.0)
    now = g.mark()
    return GuiderReport(
        status=g.status(),
        health=g.health(),
        last_minute=g.stats(now - 60, now),
        calibration=g.calibration,
        darks=g.darks.describe(),
        pixel_scale_source=g.pixel_scale_source,
    )


@router.get("/view", response_model=ViewInfo)
async def get_view(request: Request) -> ViewInfo:
    """The guide camera's latest frame, described: its size and the stars to draw on it."""
    return _guider(request).view.info()


@router.get("/frame.jpg")
async def get_frame(request: Request, v: int | None = None) -> Response:
    """The latest frame as a stretched JPEG. *v* (the view's version) only busts caches."""
    data = _guider(request).view.jpeg()
    if data is None:
        raise HTTPException(status_code=404, detail="No frame yet")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/preview", status_code=204)
async def start_preview(request: Request) -> None:
    """Show the guide camera (and the stars it would guide on) without guiding."""
    try:
        await _guider(request).start_preview()
    except GuiderError as exc:
        raise _conflict(exc) from exc


@router.delete("/preview", status_code=204)
async def stop_preview(request: Request) -> None:
    await _guider(request).stop_preview()


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
    """Exposure and gain apply at once, even while guiding; the rest at the next run."""
    g = _guider(request)
    try:
        await g.update_settings(body)
    except GuiderError as exc:
        raise _conflict(exc) from exc
    store = getattr(request.app.state, "profile_store", None)
    if store is not None:
        current = store.get_user_settings()
        updated = {**current.plugin_settings, "guider": body.model_dump()}
        store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    logger.info("guider.settings_updated")
    return body
