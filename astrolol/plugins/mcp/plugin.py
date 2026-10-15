"""MCP plugin: lets Claude and other AI assistants operate astrolol through the Model Context Protocol."""
from __future__ import annotations

from fastapi import FastAPI

from astrolol.core.auth import AclRule, Level
from astrolol.core.plugin_api import LogScope, Plugin, PluginContext, PluginManifest


class McpPlugin:
    manifest = PluginManifest(
        id="mcp",
        nav_group="settings",
        name="AI assistants (MCP)",
        version="0.1.0",
        description="Lets Claude and other AI assistants observe and operate the telescope.",
        nav_order=96,
        hot_reloadable=True,
        log_scopes=[LogScope(key="mcp", label="AI assistants (MCP)", logger="astrolol.plugins.mcp")],
        acl_rules=[
            # Every MCP call is a POST, including the read-only ones. The tools perform their
            # REST calls with the caller's own credentials, so what a caller may do is still
            # decided by the access level of those routes.
            AclRule("/plugins/mcp", Level.VIEWER, ("POST",)),
        ],
    )

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        from astrolol.plugins.mcp.api import router
        app.state.mcp_event_bus = ctx.event_bus
        app.include_router(router)

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def get_plugin() -> Plugin:
    return McpPlugin()
