"""PHD2 guiding plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from astrolol.plugins.phd2.api import router
from astrolol.core.guiding import register_guider, unregister_guider
from astrolol.plugins.phd2.client import Phd2Client
from astrolol.plugins.phd2.guider import Phd2Guider
from astrolol.plugins.phd2.settings import Phd2Settings

logger = structlog.get_logger()


class Phd2Plugin:
    manifest = PluginManifest(
        id="phd2",
        name="PHD2 Guiding",
        version="0.1.0",
        description=(
            "PHD2 autoguider integration — live connection status, guiding metrics, "
            "guide graph, and configurable automatic dithering between frames."
        ),
        nav_order=10,
        log_scopes=[LogScope(key="phd2", label="PHD2 Guiding", logger="astrolol.plugins.phd2")],
    )

    def __init__(self) -> None:
        self._client: Phd2Client | None = None
        self._guider: Phd2Guider | None = None
        self._app: FastAPI | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("phd2", Phd2Settings)

        self._client = Phd2Client(
            host=cfg.host,
            port=cfg.port,
            event_bus=ctx.event_bus,
        )
        app.state.phd2_client = self._client

        # The core guider interface (sequencer, imager loop dithering) goes through PHD2
        self._guider = Phd2Guider(self._client)
        self._app = app
        register_guider(app, self._guider)

        app.include_router(router)
        logger.info("phd2.plugin_setup", host=cfg.host, port=cfg.port)

    async def startup(self) -> None:
        pass  # PHD2 connects only on explicit user request (POST /phd2/connect)

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.stop()
        if self._app is not None and self._guider is not None:
            unregister_guider(self._app, self._guider)


def get_plugin() -> Phd2Plugin:
    return Phd2Plugin()
