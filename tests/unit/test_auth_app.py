"""The real app with the security plugin enabled: enforcement is wired end to end."""
import pytest
from fastapi.testclient import TestClient

from astrolol.config.settings import settings
from astrolol.main import create_app
from astrolol.profiles.store import ProfileStore


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for name in ("profiles_file", "inventory_file", "security_file", "service_token_file"):
        monkeypatch.setattr(settings, name, tmp_path / name)
    store = ProfileStore(settings.profiles_file)
    store.update_user_settings(store.get_user_settings().model_copy(update={"enabled_plugins": ["security"]}))
    return create_app()


def test_open_by_default_without_the_plugin(tmp_path, monkeypatch):
    for name in ("profiles_file", "inventory_file", "security_file", "service_token_file"):
        monkeypatch.setattr(settings, name, tmp_path / name)
    c = TestClient(create_app())
    assert c.get("/auth/status").json()["enforced"] is False
    assert c.get("/devices/connected").status_code == 200


def test_enforcement_end_to_end(app):
    c = TestClient(app)
    assert c.get("/devices/connected").status_code == 200  # no account yet: open
    assert c.post("/plugins/security/users", json={"name": "root", "password": "correct horse"}).status_code == 201

    anon = TestClient(app)
    assert anon.get("/devices/connected").status_code == 401
    assert anon.get("/health").status_code == 200
    assert anon.get("/").status_code in (200, 404)  # the UI shell is never gated
    assert anon.get("/plugins/security/users").status_code == 401

    assert c.get("/devices/connected").status_code == 200
    assert c.get("/plugins/security/users").status_code == 200
    # Defaults: an unannotated mutating route is operator, admin routes stay admin.
    assert c.post("/plugins/security/users", json={"name": "view", "password": "password1", "level": "viewer"}).status_code == 201
    view = TestClient(app)
    assert view.post("/auth/login", json={"username": "view", "password": "password1"}).status_code == 200
    assert view.get("/devices/connected").status_code == 200
    assert view.post("/devices/connect", json={}).status_code == 403
    assert view.put("/settings", json={}).status_code == 403
    assert view.post("/admin/restart").status_code == 403
    assert view.get("/settings").json()["plugin_settings"] == {}


def test_websocket_events_need_sign_in(app):
    from starlette.websockets import WebSocketDisconnect

    c = TestClient(app)
    c.post("/plugins/security/users", json={"name": "root", "password": "correct horse"})
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/ws/events"):
            pass


def test_no_mutating_route_is_open_to_viewers(tmp_path, monkeypatch):
    """Every POST/PUT/DELETE of the real app (all plugins on) needs operator, bar a short allowlist."""
    from astrolol.app import discover_plugins
    from astrolol.core.auth import Level

    for name in ("profiles_file", "inventory_file", "security_file", "service_token_file"):
        monkeypatch.setattr(settings, name, tmp_path / name)
    store = ProfileStore(settings.profiles_file)
    store.update_user_settings(store.get_user_settings().model_copy(
        update={"enabled_plugins": [p for p in discover_plugins() if p != "guider"]}))  # guider and guide_simulator exclude each other
    app = create_app()

    viewer_ok = {("POST", "/plugins/security/me/password")}
    public_ok = {("POST", "/auth/login"), ("POST", "/auth/logout")}
    low, seen = [], 0
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            method = method.upper()
            if method not in {"POST", "PUT", "DELETE", "PATCH"}:
                continue
            seen += 1
            public, level = app.state.acl.lookup(method, path.replace("{", "x").replace("}", ""))
            if (public and (method, path) not in public_ok) or (
                    not public and level < Level.OPERATOR and (method, path) not in viewer_ok):
                low.append((method, path))
    assert seen > 100  # the test really looked at the API
    assert low == []

    # Spot checks on the routes that can reconfigure or take over the machine.
    for method, path in [
        ("POST", "/plugins/system/reboot"), ("GET", "/plugins/system/settings"), ("PUT", "/plugins/eqmod/settings"),
        ("POST", "/plugins/lx200/start"), ("POST", "/plugins/bluetooth_serial/pair"), ("PUT", "/plugins/mdns/settings"),
        ("POST", "/plugins/platesolve/install_db"), ("GET", "/plugins/security/users"), ("PUT", "/settings"),
        ("POST", "/devices/connect"), ("POST", "/admin/restart"), ("PUT", "/profiles/p"), ("POST", "/inventory"),
    ]:
        assert app.state.acl.lookup(method, path) == (False, Level.ADMIN), (method, path)
    assert app.state.acl.lookup("GET", "/plugins/system/status") == (False, Level.VIEWER)
