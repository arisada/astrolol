"""System management plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from plugins.system.models import SystemSettings
from plugins.system.throttle import ThrottleMonitor

logger = structlog.get_logger()


class SystemPlugin:
    manifest = PluginManifest(
        id="system",
        name="System",
        version="0.1.0",
        description=(
            "Device management for the host running astrolol. "
            "Manages WiFi connections and access-point mode, "
            "shows CPU / memory / temperature / disk statistics, "
            "monitors power/thermal throttling, "
            "and provides reboot / shutdown / restart controls."
        ),
        nav_order=90,
        log_scopes=[LogScope(key="system", label="System", logger="plugins.system")],
    )

    def __init__(self) -> None:
        self._throttle_monitor: ThrottleMonitor | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from plugins.system.api import router
        app.include_router(router)

        cfg = ctx.get_plugin_settings("system", SystemSettings)
        self._throttle_monitor = ThrottleMonitor(
            enabled=cfg.throttle_monitor_enabled,
            interval_seconds=cfg.throttle_check_interval_seconds,
        )
        app.state.system_throttle_monitor = self._throttle_monitor
        logger.info("system.plugin_setup")

    async def startup(self) -> None:
        if self._throttle_monitor is not None:
            await self._throttle_monitor.start()

    async def shutdown(self) -> None:
        if self._throttle_monitor is not None:
            await self._throttle_monitor.stop()


def get_plugin() -> SystemPlugin:
    return SystemPlugin()
