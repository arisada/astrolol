"""LX200 telescope server plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from plugins.lx200.api import router
from plugins.lx200.server import Lx200Server
from plugins.lx200.settings import Lx200Settings

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
        log_scopes=[LogScope(key="lx200", label="LX200 Server", logger="plugins.lx200")],
    )

    def __init__(self) -> None:
        self._server: Lx200Server | None = None
        self._autostart = True

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("lx200", Lx200Settings)
        self._autostart = cfg.autostart

        self._server = Lx200Server(
            port=cfg.port,
            device_manager=ctx.device_manager,
            mount_manager=app.state.mount_manager,
        )
        app.state.lx200_server = self._server
        app.include_router(router)
        logger.info("lx200.plugin_setup", port=cfg.port)

    async def startup(self) -> None:
        if self._server is not None and self._autostart:
            await self._server.start()

    async def shutdown(self) -> None:
        if self._server is not None:
            await self._server.stop()


def get_plugin() -> Lx200Plugin:
    return Lx200Plugin()
