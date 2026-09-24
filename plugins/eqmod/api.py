"""EQMOD plugin API.

GET/PUT /plugins/eqmod/settings — device-specific settings that aren't part
of the shared IMount contract (see settings.py).
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from plugins.eqmod.settings import EqmodSettings

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/eqmod", tags=["eqmod"])


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

    # Apply live to any currently-connected EQMOD-family mount. Duck-typed and
    # best-effort since this knob isn't part of the shared IMount contract —
    # only eqmod_sim/eqmod adapters implement it.
    device_manager = request.app.state.device_manager
    for info in device_manager.list_connected():
        if info["kind"] != "mount":
            continue
        mount = device_manager.get_mount(info["device_id"])
        if hasattr(mount, "set_led_brightness"):
            mount.set_led_brightness(body.led_brightness)

    logger.info("eqmod.settings_updated", led_brightness=body.led_brightness)
    return body
