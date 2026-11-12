"""Stacked camera plugin: one camera for the guider and for long exposures at once.

Registers two cameras that are built on a camera already connected: one gives the guider its
short frames, the other takes exposures of any length by adding those same frames up.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.config.settings import settings
from astrolol.core.auth import AclRule, Level
from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from astrolol.plugins.stacked_camera.adapters import FAST_KEY, STACKED_KEY, bind_adapters
from astrolol.plugins.stacked_camera.api import router
from astrolol.plugins.stacked_camera.hubs import HubRegistry
from astrolol.plugins.stacked_camera.settings import StackedCameraSettings

logger = structlog.get_logger()


class StackedCameraPlugin:
    manifest = PluginManifest(
        id="stacked_camera",
        nav_group="equipment",
        name="Stacked camera",
        version="0.1.0",
        description=(
            "Guide and take long exposures with the same camera: the guider gets a frame every "
            "few seconds while the exposure builds up from the same frames."
        ),
        log_scopes=[
            LogScope(
                key="stacked_camera", label="Stacked camera",
                logger="astrolol.plugins.stacked_camera",
            )
        ],
        acl_rules=[
            # Connecting devices is administration, here as in /devices/connect.
            AclRule("/plugins/stacked_camera/attach", Level.ADMIN, ("POST",)),
            AclRule("/plugins/stacked_camera/detach", Level.ADMIN, ("POST",)),
        ],
    )

    def __init__(self) -> None:
        self._hubs: HubRegistry | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        def sub_exposure() -> float:
            return ctx.get_plugin_settings("stacked_camera", StackedCameraSettings).sub_exposure

        hubs = HubRegistry(
            ctx.device_manager,
            ctx.event_bus,
            sub_exposure,
            virtual_adapter_keys=frozenset({STACKED_KEY, FAST_KEY}),
        )
        self._hubs = hubs
        app.state.stacked_camera_hubs = hubs
        app.state.stacked_camera_ctx = ctx
        stacked, fast = bind_adapters(hubs, settings.images_dir)
        ctx.device_registry.register_camera(STACKED_KEY, stacked)
        ctx.device_registry.register_camera(FAST_KEY, fast)
        app.include_router(router)
        logger.info("stacked_camera.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        if self._hubs is not None:
            await self._hubs.shutdown()


def get_plugin() -> StackedCameraPlugin:
    return StackedCameraPlugin()
