"""EQMOD mount plugin for astrolol.

- "eqmod_sim": protocol-agnostic mount emulator (Phase 1).
- "eqmod": real Sky-Watcher driver over serial (Phase 2, bring-up build).
- Phase 3 (later): minimal INDI guide server so PHD2 can pulse-guide without indiserver.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from plugins.eqmod.api import router
from plugins.eqmod.mount import EqmodMount
from plugins.eqmod.simulator import EqmodSimMount

logger = structlog.get_logger()


class EqmodPlugin:
    manifest = PluginManifest(
        id="eqmod",
        name="EQMOD Mount",
        version="0.2.0",
        description=(
            "Native (non-INDI) driver for Sky-Watcher mounts over the motor controller "
            "protocol (EQMOD cable or built-in USB). Bring-up build: connect, nudge, "
            "tracking and live diagnostics; GoTo, sync and park follow. Also ships a "
            "mount emulator ('eqmod_sim')."
        ),
        log_scopes=[LogScope(key="eqmod", label="EQMOD", logger="plugins.eqmod")],
    )

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        ctx.device_registry.register_mount("eqmod_sim", EqmodSimMount)
        ctx.device_registry.register_mount("eqmod", EqmodMount)
        app.include_router(router)
        logger.info("eqmod.plugin_setup")

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> "EqmodPlugin":
    return EqmodPlugin()
