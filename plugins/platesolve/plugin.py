"""Plate-solving plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import PluginContext, PluginManifest
from plugins.platesolve.api import router
from plugins.platesolve.settings import PlatesolveSettings
from plugins.platesolve.solver import SolveManager

logger = structlog.get_logger()


class PlatesolvePlugin:
    manifest = PluginManifest(
        id="platesolve",
        name="Plate Solving",
        version="0.1.0",
        description=(
            "Astrometric plate solving via astap_cli. Solves FITS images to determine "
            "pointing coordinates (RA/Dec), field rotation, and pixel scale. "
            "Supports concurrent solves and cancellation."
        ),
        nav_order=20,
    )

    def __init__(self) -> None:
        self._manager: SolveManager | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("platesolve", PlatesolveSettings)

        self._manager = SolveManager(
            event_bus=ctx.event_bus,
            astap_bin=cfg.astap_bin,
            astap_db_path=cfg.astap_db_path,
        )
        app.state.solve_manager = self._manager

        app.include_router(router)
        logger.info(
            "platesolve.plugin_setup",
            astap_bin=cfg.astap_bin,
            astap_db_path=cfg.astap_db_path,
        )

    async def startup(self) -> None:
        pass  # no background loop needed

    async def shutdown(self) -> None:
        """Cancel any still-running solve tasks."""
        if self._manager is None:
            return
        for job in self._manager._jobs.values():
            if job.task is not None and not job.task.done():
                job.task.cancel()


def get_plugin() -> PlatesolvePlugin:
    return PlatesolvePlugin()
