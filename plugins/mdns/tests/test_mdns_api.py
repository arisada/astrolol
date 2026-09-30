"""Tests for the mdns plugin API and manifest."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.plugin_api import PluginContext
from plugins.mdns.plugin import MdnsPlugin, get_plugin


def _make_app() -> FastAPI:
    app = FastAPI()
    profile_store = MagicMock()
    profile_store.get_user_settings.return_value = MagicMock(plugin_settings={})
    app.state.profile_store = profile_store

    ctx = PluginContext(
        event_bus=None,
        device_manager=None,
        device_registry=None,
        profile_store=profile_store,
    )
    plugin = MdnsPlugin()
    plugin.setup(app, ctx)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


def test_get_settings_defaults(client: TestClient) -> None:
    r = client.get("/plugins/mdns/settings")
    assert r.status_code == 200
    assert r.json() == {
        "advertised_host": None,
        "advertised_port": None,
        "scheme": "http",
        "instance_name": None,
    }


def test_put_settings(client: TestClient) -> None:
    payload = {
        "advertised_host": "astrolol.example.lan",
        "advertised_port": 443,
        "scheme": "https",
        "instance_name": "Backyard Rig",
    }
    r = client.put("/plugins/mdns/settings", json=payload)
    assert r.status_code == 200
    assert r.json() == payload


def test_plugin_manifest_fields() -> None:
    plugin = get_plugin()
    assert plugin.manifest.id == "mdns"
    assert plugin.manifest.requires == []


def test_get_plugin_returns_plugin_protocol() -> None:
    from astrolol.core.plugin_api import Plugin
    plugin = get_plugin()
    assert isinstance(plugin, Plugin)


def test_plugin_setup_registers_routes() -> None:
    app = _make_app()
    client = TestClient(app)
    r = client.get("/plugins/mdns/settings")
    assert r.status_code == 200


async def test_startup_without_a_port_does_not_advertise() -> None:
    """No advertised_port configured: startup() should not raise or register anything."""
    plugin = MdnsPlugin()
    app = FastAPI()
    profile_store = MagicMock()
    profile_store.get_user_settings.return_value = MagicMock(plugin_settings={})
    app.state.profile_store = profile_store
    ctx = PluginContext(
        event_bus=None, device_manager=None, device_registry=None, profile_store=profile_store,
    )
    plugin.setup(app, ctx)
    await plugin.startup()
    assert plugin._advertiser._aiozc is None
    await plugin.shutdown()
