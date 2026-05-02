"""Target plugin — plan and slew to sky objects by name."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest

logger = structlog.get_logger()


class TargetPlugin:
    manifest = PluginManifest(
        id="target",
        name="Target",
        version="0.1.0",
        description=(
            "Search sky objects by name, view rise/set/transit times and an altitude "
            "graph, set the mount target, and manage a favourites list."
        ),
        nav_order=5,
        nav_before="mount",
        log_scopes=[LogScope(key="target", label="Target", logger="plugins.target")],
    )

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from plugins.target.api import router
        app.include_router(router)
        logger.info("target.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> TargetPlugin:
    return TargetPlugin()
