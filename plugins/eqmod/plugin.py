"""EQMOD mount plugin for astrolol.

Phase 1 (current): a generic, protocol-agnostic mount emulator
(`EqmodSimMount`, adapter_key "eqmod_sim") that validates the device-adapter
integration contract — registry wiring, the full MountManager call surface,
and reconnect-without-resync persistence — independently of the real EQMOD/
SynScan wire protocol.

Phase 2 (later): the real serial driver behind the same IMount contract,
registered as adapter_key "eqmod".

Phase 3 (later): a minimal INDI guide server so PHD2 can issue pulse-guide
corrections to whichever adapter is connected, without needing indiserver.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import PluginContext, PluginManifest
from plugins.eqmod.api import router
from plugins.eqmod.simulator import EqmodSimMount

logger = structlog.get_logger()


class EqmodPlugin:
    manifest = PluginManifest(
        id="eqmod",
        name="EQMOD Mount",
        version="0.1.0",
        description=(
            "Native (non-INDI) driver for SkyWatcher EQMOD-protocol mounts: "
            "GoTo, full sync after plate-solve, sidereal/lunar/solar tracking, "
            "nudge, and parking, with no alignment model. Currently ships a "
            "mount emulator ('eqmod_sim') that proves out the integration; "
            "the real serial driver lands in a later phase."
        ),
    )

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        ctx.device_registry.register_mount("eqmod_sim", EqmodSimMount)
        app.include_router(router)
        logger.info("eqmod.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> "EqmodPlugin":
    return EqmodPlugin()
