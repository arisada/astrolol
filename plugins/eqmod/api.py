"""EQMOD plugin API.

GET/PUT /plugins/eqmod/settings  — device-specific settings not on the IMount contract.
GET     /plugins/eqmod/diagnostics — live controller readout for connected real mounts.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from plugins.eqmod.settings import EqmodSettings

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/eqmod", tags=["eqmod"])


class AxisDiagnostics(BaseModel):
    cpr: int
    high_speed_ratio: int
    position_counts: int
    position_degrees: float
    step_period: int
    status: dict[str, bool]
    extended_status: str
    reversed: bool


class MountDiagnostics(BaseModel):
    device_id: str
    port: str | None = None
    baudrate: int | None = None
    board_version: str | None = None
    timer_freq: int | None = None
    tracking: bool = False
    tracking_mode: str | None = None
    nudging: list[str] = []
    location: list[float] | None = None  # [lat, lon, alt_m], pushed from the active profile's site
    parked: bool = False
    park_counts: list[int] | None = None
    sync_offset: dict[str, float] | None = None  # {ra_axis_h, dec_axis_deg}; None = never synced
    axes: dict[str, AxisDiagnostics] = {}
    error: str | None = None


def _connected_mounts(request: Request):
    device_manager = request.app.state.device_manager
    for info in device_manager.list_connected():
        if info["kind"] == "mount":
            yield info["device_id"], device_manager.get_mount(info["device_id"])


@router.get("/settings", response_model=EqmodSettings)
async def get_settings(request: Request) -> EqmodSettings:
    raw = request.app.state.profile_store.get_user_settings().plugin_settings.get("eqmod", {})
    return EqmodSettings(**raw)


@router.put("/settings", response_model=EqmodSettings)
async def put_settings(body: EqmodSettings, request: Request) -> EqmodSettings:
    store = request.app.state.profile_store
    current = store.get_user_settings()
    updated = {**current.plugin_settings, "eqmod": body.model_dump()}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))

    # Duck-typed: only eqmod-family adapters implement this knob.
    for device_id, mount in _connected_mounts(request):
        if hasattr(mount, "set_led_brightness"):
            try:
                await mount.set_led_brightness(body.led_brightness)
            except Exception as exc:
                logger.warning("eqmod.led_brightness_failed", device_id=device_id, error=str(exc))

    logger.info("eqmod.settings_updated", led_brightness=body.led_brightness)
    return body


@router.get("/diagnostics", response_model=list[MountDiagnostics])
async def get_diagnostics(request: Request) -> list[MountDiagnostics]:
    results: list[MountDiagnostics] = []
    for device_id, mount in _connected_mounts(request):
        if not hasattr(mount, "diagnostics"):
            continue
        try:
            results.append(MountDiagnostics(device_id=device_id, **await mount.diagnostics()))
        except Exception as exc:
            logger.warning("eqmod.diagnostics_failed", device_id=device_id, error=str(exc))
            results.append(MountDiagnostics(device_id=device_id, error=str(exc)))
    return results
