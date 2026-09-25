"""EQMOD mount plugin for astrolol.

- "eqmod": native Sky-Watcher driver over serial.
- "eqmod_sim": protocol-agnostic mount emulator.
- INDI mount proxy: an INDI driver run by astrolol's indiserver that shows the connected
  mount to INDI clients (PHD2 pulse guiding, telescope-snooping drivers).
"""
from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from plugins.eqmod.api import router
from plugins.eqmod.indi_proxy_setup import IndiProxyRegistration
from plugins.eqmod.mount import EqmodMount
from plugins.eqmod.settings import EqmodSettings
from plugins.eqmod.simulator import EqmodSimMount

logger = structlog.get_logger()


class EqmodPlugin:
    manifest = PluginManifest(
        id="eqmod",
        name="EQMOD Mount",
        version="0.3.0",
        description=(
            "Native (non-INDI) driver for Sky-Watcher mounts over the motor controller "
            "protocol (EQMOD cable or built-in USB): GoTo, sync, tracking, parking and "
            "pulse guiding. Includes a mount emulator ('eqmod_sim') and an INDI mount "
            "proxy so PHD2 and other INDI clients can use the mount through indiserver."
        ),
        log_scopes=[LogScope(key="eqmod", label="EQMOD", logger="plugins.eqmod")],
    )

    def __init__(self) -> None:
        self._ctx: PluginContext | None = None
        self._proxy: IndiProxyRegistration | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        ctx.device_registry.register_mount("eqmod_sim", EqmodSimMount)
        ctx.device_registry.register_mount("eqmod", EqmodMount)
        self._ctx = ctx
        self._proxy = IndiProxyRegistration(
            getattr(ctx.device_registry, "indi_manager", None),
            Path(getattr(ctx.device_registry, "indi_run_dir", "/tmp/astrolol")),
        )
        app.state.eqmod_indi_proxy = self._proxy
        app.include_router(router)
        logger.info("eqmod.plugin_setup")

    async def startup(self) -> None:
        if self._ctx is None or self._proxy is None:
            return
        cfg = self._ctx.get_plugin_settings("eqmod", EqmodSettings)
        await self._proxy.apply(cfg.indi_proxy_enabled, cfg.indi_proxy_api_url)

    async def shutdown(self) -> None:
        # The proxy is left loaded: indiserver outlives astrolol, and the proxy reconnects
        # to the REST API on its own once astrolol is back.
        pass


def get_plugin() -> "EqmodPlugin":
    return EqmodPlugin()
