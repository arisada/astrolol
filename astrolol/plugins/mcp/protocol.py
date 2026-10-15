"""MCP over streamable HTTP, stateless: every POST is a complete JSON-RPC exchange.

Only what tools need is implemented (initialize, ping, tools/list, tools/call). There is no
session, no server-initiated stream and no SSE: a client that opens GET gets 405, which the
specification allows. Responses are plain JSON.
"""
from __future__ import annotations

from typing import Any

import structlog

from astrolol.plugins.mcp.loopback import ToolError
from astrolol.plugins.mcp.tools import Registry, ToolContext

logger = structlog.get_logger()

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

INSTRUCTIONS = (
    "Controls an astrophotography rig (mount, camera, focuser, filter wheel, guider, sequencer) "
    "through astrolol. Start with get_overview. Check what is connected and where the mount "
    "points before moving anything, and park the mount when the session is over."
)


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


async def handle_message(msg: Any, registry: Registry, ctx: ToolContext, server_version: str) -> dict[str, Any] | None:
    """Answer one JSON-RPC message; None for notifications and responses (nothing to send back)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message")
    method = msg.get("method")
    rid = msg.get("id")
    if method is None:
        return None  # a response to a request we never sent
    if "id" not in msg:
        return None  # notification (initialized, cancelled, …)
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return _error(rid, INVALID_PARAMS, "params must be an object")

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "astrolol", "version": server_version},
            "instructions": INSTRUCTIONS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": registry.describe(ctx)}}
    if method == "tools/call":
        name = params.get("name")
        tool = registry.get(name) if isinstance(name, str) else None
        if tool is None:
            return _error(rid, INVALID_PARAMS, f"Unknown tool: {name!r}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(rid, INVALID_PARAMS, "arguments must be an object")
        return {"jsonrpc": "2.0", "id": rid, "result": await _call_tool(tool, ctx, args)}
    return _error(rid, METHOD_NOT_FOUND, f"Method not found: {method}")


async def _call_tool(tool: Any, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        content = await tool.run(ctx, args)
        return {"content": content, "isError": False}
    except ToolError as exc:
        logger.info("mcp.tool_refused", tool=tool.name, error=str(exc))
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except Exception as exc:  # a bug in a tool must not take the endpoint down
        logger.error("mcp.tool_failed", tool=tool.name, error=str(exc), exc_info=True)
        return {"content": [{"type": "text", "text": f"Internal error in {tool.name}: {exc}"}], "isError": True}
