"""Flat calibration wizard plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest

logger = structlog.get_logger()


class FlatWizardPlugin:
    manifest = PluginManifest(
        id="flat_wizard",
        name="Flat Wizard",
        version="0.1.0",
        description=(
            "Solves the correct exposure duration for flat calibration frames by trial and "
            "error (short unsaved test exposures, converging on a target percentage of the "
            "sensor's full well with no saturated pixels), one filter at a time, then queues "
            "the resulting flats on the sequencer."
        ),
        requires=["sequencer"],
        nav_order=22,
        log_scopes=[LogScope(key="flat_wizard", label="Flat Wizard", logger="plugins.flat_wizard")],
        hot_reloadable=True,
    )

    def __init__(self) -> None:
        self._engine = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from plugins.flat_wizard.api import router
        from plugins.flat_wizard.engine import FlatWizardEngine

        engine = FlatWizardEngine(app=app, event_bus=ctx.event_bus)
        app.state.flat_wizard_engine = engine
        self._engine = engine

        app.include_router(router)
        logger.info("flat_wizard.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        if self._engine is not None:
            await self._engine.abort()


def get_plugin() -> FlatWizardPlugin:
    return FlatWizardPlugin()
