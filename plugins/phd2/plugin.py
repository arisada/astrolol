"""PHD2 guiding plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import PluginContext, PluginManifest
from plugins.phd2.api import router
from plugins.phd2.client import Phd2Client

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
    )

    def __init__(self) -> None:
        self._client: Phd2Client | None = None
        self._imager_manager = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        # Read PHD2 host/port from persisted user settings
        profile_store = app.state.profile_store
        user_settings = profile_store.get_user_settings()

        self._client = Phd2Client(
            host=user_settings.phd2_host,
            port=user_settings.phd2_port,
            event_bus=ctx.event_bus,
        )
        app.state.phd2_client = self._client

        # Wire the dither hook into ImagerManager so the loop can trigger dithers
        self._imager_manager = app.state.imager_manager
        self._imager_manager._dither_fn = self._dither_fn

        app.include_router(router)
        logger.info("phd2.plugin_setup", host=user_settings.phd2_host, port=user_settings.phd2_port)

    async def startup(self) -> None:
        if self._client is not None:
            await self._client.start()

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.stop()
        if self._imager_manager is not None:
            self._imager_manager._dither_fn = None

    async def _dither_fn(self, config: "DitherConfig") -> None:  # type: ignore[name-defined]
        """Called by ImagerManager between loop frames when dither conditions are met."""
        if self._client is None:
            raise RuntimeError("PHD2 client not initialised")
        await self._client.dither(
            pixels=config.pixels,
            ra_only=config.ra_only,
            settle_pixels=config.settle_pixels,
            settle_time=config.settle_time,
            settle_timeout=config.settle_timeout,
        )


def get_plugin() -> Phd2Plugin:
    return Phd2Plugin()
