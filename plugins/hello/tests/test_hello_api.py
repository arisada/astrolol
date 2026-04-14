"""Tests for the hello plugin API."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.hello.api import HelloState, router
from plugins.hello.plugin import HelloPlugin, get_plugin


@pytest.fixture()
def client() -> TestClient:
    """Fresh FastAPI app with hello plugin set up."""
    app = FastAPI()
    plugin = HelloPlugin()
    # Simulate plugin setup
    app.state.hello_state = HelloState()
    app.include_router(router)
    return TestClient(app)


# --- API tests ---

def test_get_property_default(client: TestClient) -> None:
    r = client.get("/hello/property")
    assert r.status_code == 200
    assert r.json() == {"hello": False}


def test_set_property_true(client: TestClient) -> None:
    r = client.post("/hello/property", json={"hello": True})
    assert r.status_code == 200
    assert r.json() == {"hello": True}


def test_set_property_roundtrip(client: TestClient) -> None:
    client.post("/hello/property", json={"hello": True})
    r = client.get("/hello/property")
    assert r.json() == {"hello": True}


def test_set_property_false_after_true(client: TestClient) -> None:
    client.post("/hello/property", json={"hello": True})
    client.post("/hello/property", json={"hello": False})
    r = client.get("/hello/property")
    assert r.json() == {"hello": False}


def test_state_is_per_app() -> None:
    """Each app instance has independent state — no module-level bleed."""
    app1 = FastAPI()
    app1.state.hello_state = HelloState()
    app1.include_router(router)

    app2 = FastAPI()
    app2.state.hello_state = HelloState()
    app2.include_router(router)

    c1 = TestClient(app1)
    c2 = TestClient(app2)

    c1.post("/hello/property", json={"hello": True})
    assert c1.get("/hello/property").json() == {"hello": True}
    assert c2.get("/hello/property").json() == {"hello": False}


# --- Plugin manifest ---

def test_plugin_manifest_fields() -> None:
    plugin = get_plugin()
    assert plugin.manifest.id == "hello"
    assert plugin.manifest.name == "Hello World"
    assert plugin.manifest.version == "0.1.0"
    assert plugin.manifest.requires == []


def test_get_plugin_returns_plugin_protocol() -> None:
    from astrolol.core.plugin_api import Plugin
    plugin = get_plugin()
    assert isinstance(plugin, Plugin)


def test_plugin_setup_registers_routes() -> None:
    """setup() adds the /hello/property routes to the app."""
    from astrolol.core.plugin_api import PluginContext
    app = FastAPI()
    plugin = HelloPlugin()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    plugin.setup(app, ctx)

    client = TestClient(app)
    r = client.get("/hello/property")
    assert r.status_code == 200
