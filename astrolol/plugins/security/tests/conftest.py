from __future__ import annotations

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient

from astrolol.api.auth import router as auth_router
from astrolol.config.settings import settings as global_settings
from astrolol.core.auth import AuthMiddleware, default_acl
from astrolol.core.plugin_api import PluginContext
from astrolol.core.same_origin import SameOriginMiddleware
from astrolol.plugins.security.plugin import SecurityPlugin
from astrolol.plugins.system.plugin import SystemPlugin
from astrolol.profiles.store import ProfileStore


@pytest.fixture()
def app(tmp_path, monkeypatch) -> FastAPI:
    monkeypatch.setattr(global_settings, "security_file", tmp_path / "security.json")
    monkeypatch.setattr(global_settings, "service_token_file", tmp_path / "service_token")
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.origin_providers = []
    app.add_middleware(SameOriginMiddleware, providers=app.state.origin_providers)
    app.state.authorizer = None
    app.state.acl = default_acl()
    app.state.acl.add_plugin(*SecurityPlugin.manifest.acl_rules, *SystemPlugin.manifest.acl_rules)

    ctx = PluginContext(
        event_bus=None, device_manager=None, device_registry=None,
        profile_store=ProfileStore(tmp_path / "profiles.json"),
    )
    app.state.plugin_ctx = ctx

    app.include_router(auth_router)

    @app.get("/mount/{d}/status")
    async def status(d: str):
        return {"ok": True}

    @app.post("/mount/{d}/slew")
    async def slew(d: str):
        return {"slewing": True}

    @app.put("/settings")
    async def put_settings():
        return {"saved": True}

    @app.get("/plugins/system/settings")
    async def sys_settings():
        return {"hotspot_password": "secret"}

    @app.get("/who")
    async def who(request: Request):
        p = request.state.principal
        return {"principal": None if p is None else [p.name, p.level.label, p.kind]}

    @app.websocket("/ws/events")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_json({"hi": 1})
        await socket.close()

    SecurityPlugin().setup(app, ctx)
    return app


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app, base_url="http://astro.lan")


def create_admin(client: TestClient, name="root", password="correct horse") -> None:
    r = client.post("/plugins/security/users", json={"name": name, "password": password})
    assert r.status_code == 201, r.text


def login(client: TestClient, name: str, password: str) -> TestClient:
    r = client.post("/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return client
