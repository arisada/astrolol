"""Built-in autoguider: guides without PHD2, from a stream of frames from any camera."""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.config.settings import settings as app_settings
from astrolol.core.guiding import register_guider, unregister_guider
from astrolol.core.plugin_api import LogScope, Plugin, PluginContext, PluginManifest
from plugins.guider.api import router
from plugins.guider.darks import DarkLibrary
from plugins.guider.devices import ManagerDevices
from plugins.guider.guider import BuiltinGuider
from plugins.guider.scale import derive_pixel_scale
from plugins.guider.settings import GuiderSettings

logger = structlog.get_logger()


class GuiderPlugin:
    manifest = PluginManifest(
        id="guider",
        name="Built-in Guider",
        version="0.1.0",
        description=(
            "Autoguider that runs inside astrolol, without PHD2: it picks guide stars, "
            "calibrates itself, and corrects the mount from any camera. Don't enable it "
            "together with PHD2."
        ),
        nav_order=9,
        log_scopes=[LogScope(key="guider", label="Built-in Guider", logger="plugins.guider")],
    )

    def __init__(self) -> None:
        self._guider: BuiltinGuider | None = None
        self._app: FastAPI | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("guider", GuiderSettings)
        darks = DarkLibrary(app_settings.profiles_file.parent / "guider" / "darks")
        # The devices read the guider's *current* settings, so edits apply without a restart.
        devices = ManagerDevices(ctx.device_manager, lambda: self._guider.settings)  # type: ignore[union-attr]
        guider = BuiltinGuider(
            ctx.event_bus, cfg, devices, darks,
            scale_resolver=lambda camera_id: derive_pixel_scale(app, camera_id),
        )
        self._guider, self._app = guider, app
        app.state.builtin_guider = guider
        register_guider(app, guider)
        app.include_router(router)
        logger.info("guider.plugin_setup", guide_output=cfg.guide_output)

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        if self._guider is not None:
            await self._guider.stop()
            await self._guider.stop_preview()
            if self._app is not None:
                unregister_guider(self._app, self._guider)


def get_plugin() -> Plugin:
    return GuiderPlugin()
