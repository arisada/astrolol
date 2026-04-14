"""Hello world plugin — proof-of-concept for the plugin system."""
from __future__ import annotations

from typing import TYPE_CHECKING

from astrolol.core.plugin_api import Plugin, PluginContext, PluginManifest

if TYPE_CHECKING:
    from fastapi import FastAPI


class HelloPlugin:
    manifest = PluginManifest(
        id="hello",
        name="Hello World",
        version="0.1.0",
        description="Proof-of-concept plugin with a single toggle property.",
    )

    def setup(self, app: "FastAPI", ctx: PluginContext) -> None:
        from plugins.hello.api import HelloState, router
        app.state.hello_state = HelloState()
        app.include_router(router)

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> Plugin:
    return HelloPlugin()
