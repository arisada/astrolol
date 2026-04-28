"""Autofocus plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import PluginContext, PluginManifest

logger = structlog.get_logger()


class AutofocusPlugin:
    manifest = PluginManifest(
        id="autofocus",
        name="Autofocus",
        version="0.1.0",
        description=(
            "Automated focuser optimisation using the V-curve (FWHM vs. position) method. "
            "Takes exposures at several focuser positions, measures median star FWHM via "
            "photutils, fits a parabola, and moves to the computed optimal focus position."
        ),
        nav_order=21,
    )

    def __init__(self) -> None:
        self._engine = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from plugins.autofocus.api import router
        from plugins.autofocus.engine import AutofocusEngine
        from plugins.autofocus.star_detector import detect_stars

        engine = AutofocusEngine(
            event_bus=ctx.event_bus,
            device_manager=ctx.device_manager,
        )
        app.state.autofocus_engine = engine
        self._engine = engine

        # Register star detection with the imager so it can annotate each frame.
        async def _analyze_stars(fits_path: str) -> tuple[float, int]:
            fwhm, count, _ = await detect_stars(fits_path)
            return fwhm, count

        imager_manager = getattr(app.state, "imager_manager", None)
        if imager_manager is not None:
            imager_manager.register_star_analyzer(_analyze_stars)

        app.include_router(router)
        logger.info("autofocus.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        if self._engine is not None:
            await self._engine.abort()


def get_plugin() -> AutofocusPlugin:
    return AutofocusPlugin()
