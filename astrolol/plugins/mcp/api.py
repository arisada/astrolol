"""MCP endpoint (streamable HTTP, JSON responses) and the pages the UI shows about it."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from astrolol.plugins.mcp.loopback import ApiClient
from astrolol.plugins.mcp.protocol import INVALID_REQUEST, PARSE_ERROR, handle_message
from astrolol.plugins.mcp.tools import REGISTRY, ToolContext

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/mcp", tags=["mcp"])

SKILL_FILE = Path(__file__).parent / "skill" / "astrolol-observing" / "SKILL.md"
MAX_BODY = 1_000_000


class ToolInfo(BaseModel):
    name: str
    description: str
    read_only: bool


class McpInfo(BaseModel):
    endpoint: str
    auth_required: bool
    tools: list[ToolInfo]


def _json(payload: Any, status: int = 200) -> Response:
    return Response(json.dumps(payload), status_code=status, media_type="application/json")


async def _rpc(request: Request) -> Response:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return _json({"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "Too large"}}, 413)
    try:
        body = json.loads(raw)
    except ValueError:
        return _json({"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Invalid JSON"}}, 400)

    api = ApiClient(request.app, dict(request.headers))
    ctx = ToolContext(app=request.app, api=api, event_bus=request.app.state.mcp_event_bus)
    version = request.app.version
    try:
        if isinstance(body, list):  # a batch (older protocol revisions)
            replies = [r for m in body if (r := await handle_message(m, REGISTRY, ctx, version)) is not None]
            return _json(replies) if replies else Response(status_code=202)
        reply = await handle_message(body, REGISTRY, ctx, version)
    finally:
        await api.aclose()
    return _json(reply) if reply is not None else Response(status_code=202)


@router.post("")
async def mcp_post(request: Request) -> Response:
    """Model Context Protocol endpoint: point an MCP client at this URL."""
    return await _rpc(request)


@router.post("/", include_in_schema=False)
async def mcp_post_slash(request: Request) -> Response:
    return await _rpc(request)


@router.api_route("", methods=["GET", "DELETE"], include_in_schema=False)
@router.api_route("/", methods=["GET", "DELETE"], include_in_schema=False)
async def mcp_unsupported() -> Response:
    # No server-initiated stream and no sessions: both are optional in the transport.
    return Response(status_code=405, headers={"Allow": "POST"})


@router.get("/info", response_model=McpInfo)
async def info(request: Request) -> McpInfo:
    """The endpoint URL and the tools offered, for the settings page."""
    ctx = ToolContext(app=request.app, api=None, event_bus=None)  # type: ignore[arg-type]
    authz = getattr(request.app.state, "authorizer", None)
    return McpInfo(
        endpoint=str(request.base_url).rstrip("/") + "/plugins/mcp",
        auth_required=bool(authz is not None and authz.enforcing()),
        tools=[ToolInfo(name=t["name"], description=t["description"], read_only=t["annotations"]["readOnlyHint"])
               for t in REGISTRY.describe(ctx)],
    )


@router.get("/skill", response_class=PlainTextResponse)
async def skill() -> str:
    """The Claude skill (SKILL.md) that goes with these tools."""
    return SKILL_FILE.read_text()
