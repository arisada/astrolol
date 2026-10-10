"""Guide simulator plugin — a hardware-free guider with fault injection, for testing."""

from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.guiding import register_guider, unregister_guider
from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from astrolol.plugins.guide_simulator.api import router
from astrolol.plugins.guide_simulator.settings import GuideSimSettings
from astrolol.plugins.guide_simulator.simulator import GuideSimulator

logger = structlog.get_logger()


class GuideSimulatorPlugin:
    manifest = PluginManifest(
        id="guide_simulator",
        nav_group="equipment",
        name="Guide Simulator",
        version="0.1.0",
        description=(
            "Simulated guider (instead of PHD2) for testing without hardware: noisy guide "
            "steps, settling, dithering, and injectable faults — star loss, guiding that "
            "stops, settle failures, disconnection. Don't enable it together with PHD2."
        ),
        nav_order=11,
        log_scopes=[
            LogScope(
                key="guide_simulator", label="Guide Simulator", logger="astrolol.plugins.guide_simulator"
            )
        ],
    )

    def __init__(self) -> None:
        self._sim: GuideSimulator | None = None
        self._app: FastAPI | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("guide_simulator", GuideSimSettings)
        self._sim = GuideSimulator(ctx.event_bus, cfg)
        register_guider(app, self._sim)
        self._app = app
        app.state.guide_simulator = self._sim
        app.include_router(router)
        logger.info("guide_simulator.plugin_setup")

    async def startup(self) -> None:
        if self._sim is not None:
            await self._sim.start()

    async def shutdown(self) -> None:
        if self._sim is not None:
            await self._sim.shutdown()
            if self._app is not None:
                unregister_guider(self._app, self._sim)


def get_plugin() -> GuideSimulatorPlugin:
    return GuideSimulatorPlugin()
