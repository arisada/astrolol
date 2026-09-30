"""mDNS plugin for astrolol — advertises the server on the local network so the Android
app (or anything else) can find it via _astrolol._tcp.local. instead of a typed-in IP.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import PluginContext, PluginManifest
from plugins.mdns.models import MdnsSettings
from plugins.mdns.service import MdnsAdvertiser

logger = structlog.get_logger()


class MdnsPlugin:
    manifest = PluginManifest(
        id="mdns",
        name="mDNS Discovery",
        version="0.1.0",
        description=(
            "Advertises this astrolol server on the local network via mDNS "
            "(_astrolol._tcp.local.) so clients can find it without a typed-in IP."
        ),
        nav_order=95,
    )

    def __init__(self) -> None:
        self._advertiser = MdnsAdvertiser()
        self._ctx: PluginContext | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from plugins.mdns.api import router
        app.include_router(router)
        self._ctx = ctx
        logger.info("mdns.plugin_setup")

    async def startup(self) -> None:
        assert self._ctx is not None
        settings = self._ctx.get_plugin_settings("mdns", MdnsSettings)
        await self._advertiser.start(settings)

    async def shutdown(self) -> None:
        await self._advertiser.stop()


def get_plugin() -> MdnsPlugin:
    return MdnsPlugin()
