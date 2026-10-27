"""A small stand-in for astrolol's REST API plus the MCP router, and helpers to talk MCP."""
from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from astrolol.core.auth import AuthMiddleware, Level, Principal, default_acl
from astrolol.core.events import EventBus
from astrolol.core.events.models import MountSlewAborted, MountSlewCompleted
from astrolol.core.plugin_api import PluginContext
from astrolol.plugins.mcp.plugin import McpPlugin


class TokenAuthorizer:
    """Bearer tokens 'viewer-token' / 'operator-token'; enforcing as soon as it is installed."""

    LEVELS = {"viewer-token": Level.VIEWER, "operator-token": Level.OPERATOR}

    def enforcing(self) -> bool:
        return True

    def guest_allowed(self) -> bool:
        return False

    async def authenticate(self, conn) -> Principal | None:  # noqa: ANN001
        token = conn.headers.get("authorization", "").removeprefix("Bearer ").strip()
        level = self.LEVELS.get(token)
        return Principal(token, level, "token") if level else None

    async def login(self, username, password, client):  # noqa: ANN001
        raise NotImplementedError

    async def logout(self, session_token):  # noqa: ANN001
        pass


def make_app(*, enabled: set[str] | None = None, secure: bool = False) -> FastAPI:
    app = FastAPI(version="9.9.9")
    app.state.acl = default_acl()
    app.state.authorizer = TokenAuthorizer() if secure else None
    app.add_middleware(AuthMiddleware)
    bus = EventBus()
    app.state.event_bus = bus
    app.state.enabled_plugin_ids = {"mcp"} | (enabled or set())
    app.state.calls = []  # (method, path) of every stub call
    app.state.slew_outcome = "completed"

    plugin = McpPlugin()
    app.state.acl.add_plugin(*plugin.manifest.acl_rules)
    plugin.setup(app, PluginContext(event_bus=bus, device_manager=None, device_registry=None))

    def note(request: Request) -> None:
        request.app.state.calls.append((request.method, request.url.path))

    @app.get("/devices/connected")
    async def connected(request: Request):
        note(request)
        return [
            {"device_id": "mount_sim", "kind": "mount", "state": "connected"},
            {"device_id": "camera_sim", "kind": "camera", "state": "connected"},
            {"device_id": "focuser_sim", "kind": "focuser", "state": "connected"},
        ]

    @app.get("/profiles/active")
    async def active_profile():
        return {"id": "p1", "name": "Backyard", "devices": []}

    @app.get("/mount/{dev}/status")
    async def mount_status(dev: str, request: Request):
        note(request)
        return {"state": "connected", "ra": 5.5, "dec": -5.4, "is_slewing": False, "is_tracking": True,
                "is_parked": False, "alt": 40.0, "az": 120.0, "pier_side": "East"}

    @app.put("/mount/{dev}/target")
    async def set_target(dev: str, request: Request):
        note(request)
        return await request.json()

    @app.get("/mount/{dev}/target")
    async def get_target(dev: str):
        return {"ra": 83.8, "dec": -5.4, "name": "M42"}

    @app.post("/mount/{dev}/slew", status_code=202)
    async def slew(dev: str, request: Request):
        note(request)
        bus_: EventBus = request.app.state.event_bus

        async def finish() -> None:
            await asyncio.sleep(0.05)
            if request.app.state.slew_outcome == "never":
                return
            if request.app.state.slew_outcome == "aborted":
                await bus_.publish(MountSlewAborted(device_id=dev))
            else:
                await bus_.publish(MountSlewCompleted(device_id=dev, ra=83.8, dec=-5.4))

        asyncio.get_running_loop().create_task(finish())
        return {"status": "slewing", "device_id": dev}

    @app.post("/mount/{dev}/stop", status_code=204, response_model=None)
    async def stop(dev: str, request: Request):
        note(request)

    @app.post("/imager/{dev}/halt", status_code=204, response_model=None)
    async def halt(dev: str, request: Request):
        note(request)

    @app.post("/focuser/{dev}/halt", status_code=204, response_model=None)
    async def fhalt(dev: str, request: Request):
        note(request)

    @app.get("/imager/{dev}/status")
    async def imager_status(dev: str):
        return {"device_id": dev, "state": "idle"}

    @app.get("/focuser/{dev}/status")
    async def focuser_status(dev: str):
        return {"state": "connected", "position": 5000, "is_moving": False}

    @app.post("/imager/{dev}/expose", status_code=201)
    async def expose(dev: str, request: Request):
        note(request)
        body = await request.json()
        if body["duration"] > 600:
            raise HTTPException(status_code=409, detail="Camera busy")
        return {"device_id": dev, "fits_path": "/data/a.fits", "preview_path": "/x.jpg", "duration": body["duration"],
                "width": 4000, "height": 3000}

    @app.get("/imager/{dev}/stats")
    async def stats(dev: str):
        return {"median": 1200.0}

    @app.get("/imager/{dev}/preview.jpg")
    async def preview(dev: str):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (2000, 1500), (40, 40, 40)).save(buf, "JPEG")
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.get("/events/history")
    async def history(request: Request):
        return [e.model_dump(mode="json") for e in request.app.state.event_bus.get_history()]

    @app.get("/secret")
    async def secret():
        return {"x": 1}

    return app


@pytest.fixture()
def app() -> FastAPI:
    return make_app()


class Mcp:
    """Minimal MCP client over TestClient."""

    def __init__(self, client: TestClient, headers: dict[str, str] | None = None) -> None:
        self.client = client
        self.headers = headers or {}
        self._id = 0

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        r = self.client.post("/plugins/mcp", headers=self.headers,
                             json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        assert r.status_code == 200, r.text
        return r.json()

    def call(self, tool: str, /, **arguments: Any) -> dict[str, Any]:
        out = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        assert "result" in out, out
        return out["result"]

    @staticmethod
    def text(result: dict[str, Any]) -> str:
        return "".join(c["text"] for c in result["content"] if c["type"] == "text")


@pytest.fixture()
def mcp(app: FastAPI):
    with TestClient(app) as client:
        yield Mcp(client)
