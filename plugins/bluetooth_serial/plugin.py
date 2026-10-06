"""Bluetooth Serial plugin — pairing/trust UI for classic Bluetooth SPP devices.

Owns the human-driven part only: scan, pair, PIN entry, rename, forget. The
actual transport (astrolol/devices/bluetooth/) is core infrastructure, used
directly by device adapters (e.g. plugins/eqmod's native driver) that want a
Bluetooth-backed serial link — this plugin never appears on their import path,
and they never see a MAC address or RFCOMM channel number.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from astrolol.core.plugin_api import LogScope, Plugin, PluginContext, PluginManifest
from plugins.bluetooth_serial.api import router

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger()


class BluetoothSerialPlugin:
    manifest = PluginManifest(
        id="bluetooth_serial",
        name="Bluetooth Serial",
        version="0.1.0",
        description=(
            "Pair and trust classic Bluetooth serial (SPP) devices — e.g. an EQMOD "
            "cable replacement — so device adapters can use them like any other "
            "serial port, with no MAC address or channel number to configure."
        ),
        log_scopes=[LogScope(key="bluetooth", label="Bluetooth", logger="plugins.bluetooth_serial")],
        hot_reloadable=True,
    )

    def setup(self, app: "FastAPI", ctx: PluginContext) -> None:
        app.include_router(router)
        logger.info("bluetooth_serial.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> Plugin:
    return BluetoothSerialPlugin()
