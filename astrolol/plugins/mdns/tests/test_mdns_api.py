"""Tests for the mdns plugin API and manifest."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.plugin_api import PluginContext
from astrolol.plugins.mdns.plugin import MdnsPlugin, get_plugin


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
        "advertised_port": None,
        "scheme": "http",
        "instance_name": None,
    }


def test_put_settings(client: TestClient) -> None:
    payload = {
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


async def test_startup_advertises_on_the_default_port_and_shutdown_withdraws_it(monkeypatch) -> None:
    """Without any settings, the server is still advertised (port = the one astrolol binds)."""
    from astrolol.plugins.mdns import service

    registered: list = []
    unregistered: list = []

    class FakeZeroconf:
        async def async_register_service(self, info):
            registered.append(info)

        async def async_unregister_service(self, info):
            unregistered.append(info)

        async def async_close(self):
            pass

    monkeypatch.setattr(service, "AsyncZeroconf", FakeZeroconf)
    monkeypatch.setattr(service.ifaddr, "get_adapters", lambda: [])

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
    assert [i.port for i in registered] == [8000]
    await plugin.shutdown()
    assert unregistered == registered


def test_a_saved_advertised_host_from_an_older_version_is_ignored() -> None:
    from astrolol.plugins.mdns.models import MdnsSettings

    assert MdnsSettings(**{"advertised_host": "old.example", "advertised_port": 443}).advertised_port == 443
