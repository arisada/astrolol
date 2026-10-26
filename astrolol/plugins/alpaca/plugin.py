"""ASCOM Alpaca plugin for astrolol.

Adapters for Alpaca devices on the network (built-in Alpaca, ASCOM Remote, OmniSim): camera,
mount, focuser, filter wheel, rotator, flat panel. Each connects to one device: connect params
``host``, ``port``, ``device_number``.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.auth import AclRule, Level
from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from astrolol.plugins.alpaca.api import router
from astrolol.plugins.alpaca.camera import AlpacaCamera
from astrolol.plugins.alpaca.filter_wheel import AlpacaFilterWheel
from astrolol.plugins.alpaca.flat_panel import AlpacaFlatPanel
from astrolol.plugins.alpaca.focuser import AlpacaFocuser
from astrolol.plugins.alpaca.mount import AlpacaMount
from astrolol.plugins.alpaca.rotator import AlpacaRotator

logger = structlog.get_logger()


class AlpacaPlugin:
    manifest = PluginManifest(
        id="alpaca",
        nav_group="equipment",
        name="ASCOM Alpaca",
        version="0.1.0",
        description=(
            "Cameras, mounts, focusers, filter wheels, rotators and flat panels that speak "
            "ASCOM Alpaca over the network."
        ),
        log_scopes=[LogScope(key="alpaca", label="Alpaca", logger="astrolol.plugins.alpaca")],
        acl_rules=[
            # Scanning sends requests to the addresses it is given: as for connecting devices.
            AclRule("/plugins/alpaca/discover", Level.ADMIN, ("POST",)),
            AclRule("/plugins/alpaca/settings", Level.ADMIN, ("PUT",)),
        ],
    )

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        registry = ctx.device_registry
        registry.register_camera(AlpacaCamera.ADAPTER_KEY, AlpacaCamera)
        registry.register_mount(AlpacaMount.ADAPTER_KEY, AlpacaMount)
        registry.register_focuser(AlpacaFocuser.ADAPTER_KEY, AlpacaFocuser)
        registry.register_filter_wheel(AlpacaFilterWheel.ADAPTER_KEY, AlpacaFilterWheel)
        registry.register_rotator(AlpacaRotator.ADAPTER_KEY, AlpacaRotator)
        registry.register_flat_panel(AlpacaFlatPanel.ADAPTER_KEY, AlpacaFlatPanel)
        app.include_router(router)
        logger.info("alpaca.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> AlpacaPlugin:
    return AlpacaPlugin()
