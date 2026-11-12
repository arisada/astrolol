"""REST API of the stacked camera: settings, status, and putting it on a camera."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.core.errors import DeviceAlreadyConnectedError, DeviceConnectionError
from astrolol.devices.config import DeviceConfig
from astrolol.plugins.stacked_camera.adapters import FAST_KEY, STACKED_KEY
from astrolol.plugins.stacked_camera.hubs import HubRegistry, SourceNotConnected
from astrolol.plugins.stacked_camera.settings import StackedCameraSettings

router = APIRouter(prefix="/plugins/stacked_camera", tags=["stacked_camera"])


class SourceRequest(BaseModel):
    source_id: str


class Attached(BaseModel):
    stacked: str  # device id of the camera that takes the long exposures
    fast: str  # device id of the camera that streams the short frames


class CameraChoice(BaseModel):
    device_id: str
    attached: Attached | None = None


class SourceStatus(BaseModel):
    source_id: str
    running: bool
    sub_exposure: float
    gain: int | None = None
    binning: int = 1
    frames: int = 0
    dropped: int = 0
    duty: float | None = None  # share of the time the sensor is exposing
    error: str | None = None


class StackedStatus(BaseModel):
    cameras: list[CameraChoice]
    sources: list[SourceStatus]


def _hubs(request: Request) -> HubRegistry:
    hubs: HubRegistry = request.app.state.stacked_camera_hubs
    return hubs


@router.get("/settings", response_model=StackedCameraSettings)
async def get_settings(request: Request) -> StackedCameraSettings:
    plugin_settings = request.app.state.profile_store.get_user_settings().plugin_settings
    return StackedCameraSettings(**plugin_settings.get("stacked_camera", {}))


@router.put("/settings", response_model=StackedCameraSettings)
async def put_settings(body: StackedCameraSettings, request: Request) -> StackedCameraSettings:
    store = request.app.state.profile_store
    current = store.get_user_settings()
    updated = {**current.plugin_settings, "stacked_camera": body.model_dump()}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    return body


@router.get("/status", response_model=StackedStatus)
async def get_status(request: Request) -> StackedStatus:
    hubs = _hubs(request)
    attached = hubs.attached()
    cameras = [
        CameraChoice(
            device_id=source_id,
            attached=(
                Attached(stacked=found[STACKED_KEY], fast=found[FAST_KEY])
                if STACKED_KEY in (found := attached.get(source_id, {})) and FAST_KEY in found
                else None
            ),
        )
        for source_id in hubs.real_cameras()
    ]
    sources = []
    for source_id, hub in hubs.hubs().items():
        stats = hub.stats
        sources.append(
            SourceStatus(
                source_id=source_id,
                running=hub.running,
                sub_exposure=hub.params.exposure,
                gain=hub.params.gain,
                binning=hub.params.binning,
                frames=stats.frames,
                dropped=stats.source_dropped,
                duty=stats.duty,
                error=None if hub.error is None else str(hub.error),
            )
        )
    return StackedStatus(cameras=cameras, sources=sources)


@router.post("/attach", response_model=Attached)
async def attach(body: SourceRequest, request: Request) -> Attached:
    """Connect the stacked and the fast camera on a connected camera (as ``<id>_stack`` and
    ``<id>_fast``). A half already connected is kept."""
    hubs = _hubs(request)
    manager = request.app.state.stacked_camera_ctx.device_manager
    try:
        hubs.camera(body.source_id)
    except SourceNotConnected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    found = hubs.attached().get(body.source_id, {})
    result: dict[str, str] = {}
    for key, suffix in ((STACKED_KEY, "stack"), (FAST_KEY, "fast")):
        if key in found:
            result[key] = found[key]
            continue
        try:
            config = DeviceConfig(
                device_id=f"{body.source_id}_{suffix}",
                kind="camera",
                adapter_key=key,
                params={"source_id": body.source_id},
            )
            await manager.connect(config)
        except ValueError as exc:  # not a usable device id
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (DeviceAlreadyConnectedError, DeviceConnectionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        result[key] = config.device_id
    return Attached(stacked=result[STACKED_KEY], fast=result[FAST_KEY])


@router.post("/detach", status_code=204, response_model=None)
async def detach(body: SourceRequest, request: Request) -> None:
    """Disconnect the stacked and the fast camera built on *source_id* (the real one stays)."""
    hubs = _hubs(request)
    manager = request.app.state.stacked_camera_ctx.device_manager
    found = hubs.attached().get(body.source_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Nothing is built on '{body.source_id}'")
    for key in (FAST_KEY, STACKED_KEY):  # the stream's user first
        if key in found:
            await manager.disconnect(found[key])
