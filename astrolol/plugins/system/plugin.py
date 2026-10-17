"""System management plugin for astrolol."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.auth import AclRule, Level
from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from astrolol.plugins.system.autonetwork import NetworkWatchdog
from astrolol.plugins.system.models import SystemSettings
from astrolol.plugins.system.throttle import ThrottleMonitor

logger = structlog.get_logger()


class SystemPlugin:
    manifest = PluginManifest(
        id="system",
        nav_group="settings",
        name="System",
        version="0.1.0",
        description=(
            "Device management for the host running astrolol. "
            "Manages WiFi connections and access-point mode, opening the hotspot by itself when no known network is around, "
            "shows CPU / memory / temperature / disk statistics, "
            "monitors power/thermal throttling, "
            "and provides reboot / shutdown / restart controls."
        ),
        nav_order=90,
        log_scopes=[LogScope(key="system", label="System", logger="astrolol.plugins.system")],
        acl_rules=[
            AclRule("/plugins/system/status", Level.VIEWER, ("GET",)),
            AclRule("/plugins/system/throttled", Level.VIEWER, ("GET",)),
            AclRule("/plugins/system/network", Level.VIEWER, ("GET",)),
            AclRule("/plugins/system/usb", Level.VIEWER, ("GET",)),
            AclRule("/plugins/system/storage", Level.VIEWER, ("GET",)),
            AclRule("/plugins/system/time", Level.VIEWER, ("GET",)),
            AclRule("/plugins/system/hostname", Level.VIEWER, ("GET",)),
            AclRule("/plugins/system/**", Level.ADMIN),
        ],
    )

    def __init__(self) -> None:
        self._throttle_monitor: ThrottleMonitor | None = None
        self._network_watchdog: NetworkWatchdog | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from astrolol.plugins.system.api import router
        app.include_router(router)

        cfg = ctx.get_plugin_settings("system", SystemSettings)
        self._throttle_monitor = ThrottleMonitor(
            enabled=cfg.throttle_monitor_enabled,
            interval_seconds=cfg.throttle_check_interval_seconds,
        )
        app.state.system_throttle_monitor = self._throttle_monitor
        self._network_watchdog = NetworkWatchdog(
            lambda: ctx.get_plugin_settings("system", SystemSettings)
        )
        app.state.system_network_watchdog = self._network_watchdog
        logger.info("system.plugin_setup")

    async def startup(self) -> None:
        if self._throttle_monitor is not None:
            await self._throttle_monitor.start()
        if self._network_watchdog is not None:
            await self._network_watchdog.start()

    async def shutdown(self) -> None:
        if self._throttle_monitor is not None:
            await self._throttle_monitor.stop()
        if self._network_watchdog is not None:
            await self._network_watchdog.stop()


def get_plugin() -> SystemPlugin:
    return SystemPlugin()
