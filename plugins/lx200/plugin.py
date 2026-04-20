"""LX200 telescope server plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import PluginContext, PluginManifest
from plugins.lx200.api import router
from plugins.lx200.server import Lx200Server

logger = structlog.get_logger()


class Lx200Plugin:
    manifest = PluginManifest(
        id="lx200",
        name="LX200 Server",
        version="0.1.0",
        description=(
            "Virtual LX200 telescope server. Connect Stellarium, SkySafari, "
            "Cartes du Ciel, TheSkyX, Voyager, or any LX200-compatible "
            "planetarium app to display the mount position and issue "
            "GoTo / Sync commands."
        ),
    )

    def __init__(self) -> None:
        self._server: Lx200Server | None = None
        self._autostart = True

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        user_settings = app.state.profile_store.get_user_settings()
        self._autostart = user_settings.lx200_autostart

        self._server = Lx200Server(
            port=user_settings.lx200_port,
            device_manager=ctx.device_manager,
            mount_manager=app.state.mount_manager,
        )
        app.state.lx200_server = self._server
        app.include_router(router)
        logger.info("lx200.plugin_setup", port=user_settings.lx200_port)

    async def startup(self) -> None:
        if self._server is not None and self._autostart:
            await self._server.start()

    async def shutdown(self) -> None:
        if self._server is not None:
            await self._server.stop()


def get_plugin() -> Lx200Plugin:
    return Lx200Plugin()
