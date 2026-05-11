"""System management plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest

logger = structlog.get_logger()


class SystemPlugin:
    manifest = PluginManifest(
        id="system",
        name="System",
        version="0.1.0",
        description=(
            "Device management for the host running astrolol. "
            "Manages WiFi connections and access-point mode (like ZWO ASIAIR), "
            "shows CPU / memory / temperature / disk statistics, "
            "and provides reboot / shutdown / restart controls."
        ),
        nav_order=90,
        log_scopes=[LogScope(key="system", label="System", logger="plugins.system")],
    )

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from plugins.system.api import router
        app.include_router(router)
        logger.info("system.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> SystemPlugin:
    return SystemPlugin()
