"""End-to-end test: PUT /settings hot-enables a hot_reloadable plugin without
a restart, and leaves a non-hot_reloadable plugin pending until one."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi.responses import HTMLResponse

from astrolol.api.settings import router as settings_router
from astrolol.core.plugin_api import PluginContext, PluginManifest
from astrolol.profiles.store import ProfileStore
from plugins.hello.plugin import HelloPlugin


class _StubPlugin:
    """A discovered-but-not-hot-reloadable plugin, to verify it stays inert."""

    manifest = PluginManifest(id="stub", name="Stub", version="0.1.0", hot_reloadable=False)

    def __init__(self) -> None:
        self.setup_called = False

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        self.setup_called = True

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, FastAPI, _StubPlugin]:
    app = FastAPI()
    store = ProfileStore(tmp_path / "profiles.json")
    stub = _StubPlugin()
    hello = HelloPlugin()

    app.state.profile_store = store
    app.state.discovered_plugins = {"hello": hello, "stub": stub}
    app.state.enabled_plugin_ids = set()
    app.state.log_scopes = []
    app.state.plugin_ctx = PluginContext(
        event_bus=None, device_manager=None, device_registry=None, profile_store=store,
    )
    app.include_router(settings_router)

    return TestClient(app), app, stub


def test_put_settings_hot_enables_hot_reloadable_plugin(client) -> None:
    tc, app, _stub = client

    current = tc.get("/settings").json()
    r = tc.put("/settings", json={**current, "enabled_plugins": ["hello"]})

    assert r.status_code == 200
    assert app.state.enabled_plugin_ids == {"hello"}
    # setup() registered hello's routes live, with no restart
    assert tc.get("/plugins/hello/property").status_code == 200


def test_hot_enabled_plugin_routes_survive_the_spa_catch_all(tmp_path: Path) -> None:
    """Regression: in production mode, mount_ui() registers a GET "/{full_path:path}"
    catch-all at startup — *before* any plugin hot-enabled afterward gets to
    app.include_router() at runtime. Starlette matches routes in list order and stops
    at the first full match, so without reordering, the catch-all (registered first)
    swallows every request under the newly hot-enabled plugin's prefix before its own
    routes are ever reached."""
    app = FastAPI()
    store = ProfileStore(tmp_path / "profiles.json")
    hello = HelloPlugin()

    app.state.profile_store = store
    app.state.discovered_plugins = {"hello": hello}
    app.state.enabled_plugin_ids = set()
    app.state.log_scopes = []
    app.state.plugin_ctx = PluginContext(
        event_bus=None, device_manager=None, device_registry=None, profile_store=store,
    )
    app.include_router(settings_router)

    # Mirrors mount_ui()'s catch-all: same name, registered last at startup, before
    # any plugin gets hot-enabled.
    @app.get("/{full_path:path}", name="spa_fallback")
    async def spa_fallback(full_path: str) -> HTMLResponse:
        return HTMLResponse("<html>spa shell</html>")

    tc = TestClient(app)
    current = tc.get("/settings").json()
    tc.put("/settings", json={**current, "enabled_plugins": ["hello"]})

    r = tc.get("/plugins/hello/property")
    assert r.status_code == 200
    assert r.json() == {"hello": False}  # hello's real handler, not the SPA shell


def test_put_settings_leaves_non_hot_reloadable_plugin_pending(client) -> None:
    tc, app, stub = client

    current = tc.get("/settings").json()
    r = tc.put("/settings", json={**current, "enabled_plugins": ["hello", "stub"]})

    assert r.status_code == 200
    assert app.state.enabled_plugin_ids == {"hello"}
    assert stub.setup_called is False
    # persisted intent still records the user's request
    assert set(tc.get("/settings").json()["enabled_plugins"]) == {"hello", "stub"}
