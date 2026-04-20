"""Stellarium telescope server plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import PluginContext, PluginManifest
from plugins.stellarium.api import router
from plugins.stellarium.server import StellariumServer

logger = structlog.get_logger()


class StellariumPlugin:
    manifest = PluginManifest(
        id="stellarium",
        name="Stellarium Server",
        version="0.1.0",
        description=(
            "Stellarium telescope server. In Stellarium's Telescope Control "
            "plugin, choose \"3rd party software or remote\" → TCP and point "
            "it at this host and port. The mount's position is pushed live "
            "and GoTo commands from Stellarium slew the mount."
        ),
    )

    def __init__(self) -> None:
        self._server: StellariumServer | None = None
        self._autostart = True

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        user_settings = app.state.profile_store.get_user_settings()
        self._autostart = user_settings.stellarium_autostart

        self._server = StellariumServer(
            port=user_settings.stellarium_port,
            device_manager=ctx.device_manager,
            mount_manager=app.state.mount_manager,
        )
        app.state.stellarium_server = self._server
        app.include_router(router)
        logger.info("stellarium.plugin_setup", port=user_settings.stellarium_port)

    async def startup(self) -> None:
        if self._server is not None and self._autostart:
            await self._server.start()

    async def shutdown(self) -> None:
        if self._server is not None:
            await self._server.stop()


def get_plugin() -> StellariumPlugin:
    return StellariumPlugin()
