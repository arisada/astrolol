"""Stellarium telescope server plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from plugins.stellarium.api import router
from plugins.stellarium.server import StellariumServer
from plugins.stellarium.settings import StellariumSettings

logger = structlog.get_logger()


class StellariumPlugin:
    manifest = PluginManifest(
        id="stellarium",
        nav_group="equipment",
        name="Stellarium Server",
        version="0.1.0",
        description=(
            "Stellarium telescope server, watch the mount's position from Stellarium"
        ),
        log_scopes=[LogScope(key="stellarium", label="Stellarium Server", logger="plugins.stellarium")],
        # Not hot_reloadable: startup() binds a TCP server socket and setup()
        # reads app.state.mount_manager unguarded — both assume boot-time
        # ordering and a restart-clean process.
    )

    def __init__(self) -> None:
        self._server: StellariumServer | None = None
        self._autostart = True

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("stellarium", StellariumSettings)
        self._autostart = cfg.autostart

        self._server = StellariumServer(
            port=cfg.port,
            device_manager=ctx.device_manager,
            mount_manager=app.state.mount_manager,
        )
        app.state.stellarium_server = self._server
        app.include_router(router)
        logger.info("stellarium.plugin_setup", port=cfg.port)

    async def startup(self) -> None:
        if self._server is not None and self._autostart:
            await self._server.start()

    async def shutdown(self) -> None:
        if self._server is not None:
            await self._server.stop()


def get_plugin() -> StellariumPlugin:
    return StellariumPlugin()
