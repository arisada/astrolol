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
from astrolol.plugins.eqmod.api import router
from astrolol.plugins.eqmod.indi_proxy_setup import IndiProxyRegistration
from astrolol.plugins.eqmod.mount import EqmodMount
from astrolol.plugins.eqmod.settings import EqmodSettings
from astrolol.plugins.eqmod.simulator import EqmodSimMount

logger = structlog.get_logger()


class EqmodPlugin:
    manifest = PluginManifest(
        id="eqmod",
        nav_group="equipment",
        name="EQMOD Mount",
        version="0.3.0",
        description=(
            "Native driver for Sky-Watcher mounts (UART, USB, Bluetooth), with a mount "
            "simulator and an INDI mount proxy for PHD2 and other INDI clients."
        ),
        log_scopes=[LogScope(key="eqmod", label="EQMOD", logger="astrolol.plugins.eqmod")],
    )

    def __init__(self) -> None:
        self._ctx: PluginContext | None = None
        self._proxy: IndiProxyRegistration | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        ctx.device_registry.register_mount("eqmod_sim", EqmodSimMount)
        # Factory (not EqmodMount directly) injects the shared BluetoothManager so a
        # mount configured with "bluetooth_device_id" can open an RFCOMM link without
        # eqmod importing the bluetooth_serial plugin (or knowing it exists) — see
        # astrolol/devices/bluetooth/. DEFAULT_CONNECT_PARAMS is copied over so the
        # "Load driver" form still prefills the same default as a plain EqmodMount.
        def _eqmod_factory(**params: object) -> EqmodMount:
            return EqmodMount(bluetooth_manager=ctx.bluetooth_manager, **params)

        _eqmod_factory.DEFAULT_CONNECT_PARAMS = EqmodMount.DEFAULT_CONNECT_PARAMS
        ctx.device_registry.register_mount("eqmod", _eqmod_factory)
        self._ctx = ctx
        self._proxy = IndiProxyRegistration(
            getattr(ctx.device_registry, "indi_manager", None),
            Path(getattr(ctx.device_registry, "indi_run_dir", "/tmp/astrolol")),
        )
        app.state.eqmod_indi_proxy = self._proxy
        imager_manager = getattr(app.state, "imager_manager", None)
        if imager_manager is not None:
            imager_manager.set_eqmod_proxy_status_fn(self._proxy.status)
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
