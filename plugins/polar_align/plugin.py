"""Polar-alignment plugin for astrolol.

Part 2 (the plate-solve wizard) and Part 1 (the polar scope reticle view) are both wired
up here. Part 1 needs no engine of its own -- it's stateless request/response math plus
calibration persisted in UserSettings.plugin_settings, see reticle.py and api.py.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest

logger = structlog.get_logger()


class PolarAlignPlugin:
    manifest = PluginManifest(
        id="polar_align",
        name="Polar Alignment",
        version="0.1.0",
        description=(
            "Polar scope reticle view and a plate-solve wizard that slews the mount "
            "through several points, fits its actual mechanical pole offset from true "
            "north/south, and guides altitude/azimuth adjustment."
        ),
        # No hard `requires`: the wizard checks for solve_manager itself at run time and
        # fails that one run cleanly if platesolve isn't enabled, rather than forcing it
        # on for anyone who only wants the (not yet built) reticle view.
        log_scopes=[LogScope(key="polar_align", label="Polar Alignment", logger="plugins.polar_align")],
        hot_reloadable=True,
    )

    def __init__(self) -> None:
        self._engine = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from plugins.polar_align.api import router
        from plugins.polar_align.wizard import WizardEngine

        engine = WizardEngine(app, ctx.event_bus)
        app.state.polar_align_engine = engine
        self._engine = engine

        app.include_router(router)
        logger.info("polar_align.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        if self._engine is not None:
            await self._engine.cancel()


def get_plugin() -> PolarAlignPlugin:
    return PolarAlignPlugin()
