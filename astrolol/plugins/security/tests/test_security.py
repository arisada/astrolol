from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from astrolol.core.auth import Level
from astrolol.plugins.security.authorizer import LoginThrottle
from astrolol.plugins.security.passwords import hash_password, verify_password
from astrolol.plugins.security.tests.conftest import create_admin, login


def anon(app) -> TestClient:
    return TestClient(app, base_url="http://astro.lan")


# ── default: open ────────────────────────────────────────────────────────────

def test_open_until_first_user(client):
    assert client.post("/mount/m/slew").status_code == 200
    s = client.get("/auth/status").json()
    assert s["enforced"] is False and s["level"] == "admin"


def test_first_user_is_admin_and_signed_in(client):
    r = client.post("/plugins/security/users", json={"name": "root", "password": "correct horse", "level": "viewer"})
    assert r.status_code == 201 and r.json()["level"] == "admin"
    assert "astrolol_session" in client.cookies
    s = client.get("/auth/status").json()
    assert s["enforced"] and s["authenticated"] and s["name"] == "root" and s["level"] == "admin"


def test_enforced_after_first_user(client, app):
    create_admin(client)
    other = anon(app)
    assert other.get("/mount/m/status").status_code == 401
    assert other.get("/auth/status").json()["authenticated"] is False


# ── login ────────────────────────────────────────────────────────────────────

def test_login_logout(client, app):
    create_admin(client)
    c = anon(app)
    assert c.post("/auth/login", json={"username": "root", "password": "nope nope"}).status_code == 401
    login(c, "ROOT", "correct horse")  # user names are case-insensitive
    assert c.get("/mount/m/status").status_code == 200
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/mount/m/status").status_code == 401


def test_session_cookie_flags(client, app):
    create_admin(client)
    r = anon(app).post("/auth/login", json={"username": "root", "password": "correct horse"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" not in cookie
    r = anon(app).post("/auth/login", json={"username": "root", "password": "correct horse"},
                       headers={"X-Forwarded-Proto": "https"})
    assert "secure" in r.headers["set-cookie"].lower()


def test_login_throttled(client, app):
    create_admin(client)
    c = anon(app)
    for _ in range(5):
        assert c.post("/auth/login", json={"username": "root", "password": "bad bad bad"}).status_code == 401
    r = c.post("/auth/login", json={"username": "root", "password": "correct horse"})
    assert r.status_code == 429 and "retry-after" in r.headers


def test_throttle_window_expires():
    t = [0.0]
    th = LoginThrottle(clock=lambda: t[0])
    for _ in range(5):
        th.failed("bob", "h")
    with pytest.raises(Exception):
        th.check("bob", "h")
    t[0] = 400
    th.check("bob", "h")


def test_password_hashing():
    h = hash_password("hunter22!")
    assert verify_password("hunter22!", h) and not verify_password("hunter23!", h)
    assert not verify_password("x", "garbage")


def test_password_not_stored_in_clear(client, tmp_path):
    create_admin(client)
    assert "correct horse" not in (tmp_path / "security.json").read_text()
    assert ((tmp_path / "security.json").stat().st_mode & 0o777) == 0o600


# ── levels ───────────────────────────────────────────────────────────────────

def _user(client, name, level):
    r = client.post("/plugins/security/users", json={"name": name, "password": "password1", "level": level})
    assert r.status_code == 201, r.text


def test_levels(client, app):
    create_admin(client)
    _user(client, "op", "operator")
    _user(client, "view", "viewer")

    op = login(anon(app), "op", "password1")
    assert op.get("/mount/m/status").status_code == 200
    assert op.post("/mount/m/slew").status_code == 200
    assert op.put("/settings").status_code == 403
    assert op.get("/plugins/security/users").status_code == 403
    assert op.get("/plugins/system/settings").status_code == 403

    view = login(anon(app), "view", "password1")
    assert view.get("/mount/m/status").status_code == 200
    r = view.post("/mount/m/slew")
    assert r.status_code == 403 and "operator" in r.json()["detail"]
    assert view.put("/settings").status_code == 403

    assert client.put("/settings").status_code == 200
    assert client.get("/plugins/system/settings").status_code == 200


def test_viewer_can_change_own_password_only(client, app):
    create_admin(client)
    _user(client, "view", "viewer")
    v = login(anon(app), "view", "password1")
    r = v.post("/plugins/security/me/password", json={"current_password": "wrong one", "new_password": "newpassword1"})
    assert r.status_code == 403
    r = v.post("/plugins/security/me/password", json={"current_password": "password1", "new_password": "newpassword1"})
    assert r.status_code == 204
    assert v.get("/mount/m/status").status_code == 401  # sessions end with the password
    login(anon(app), "view", "newpassword1")


def test_cannot_remove_last_admin(client):
    create_admin(client)
    assert client.delete("/plugins/security/users/root").status_code == 409
    assert client.put("/plugins/security/users/root", json={"level": "viewer"}).status_code == 409
    _user(client, "second", "admin")
    assert client.delete("/plugins/security/users/root").status_code == 204


def test_deleted_user_loses_session(client, app):
    create_admin(client)
    _user(client, "op", "operator")
    op = login(anon(app), "op", "password1")
    client.delete("/plugins/security/users/op")
    assert op.get("/mount/m/status").status_code == 401


def test_level_change_applies_to_existing_session(client, app):
    create_admin(client)
    _user(client, "op", "operator")
    op = login(anon(app), "op", "password1")
    client.put("/plugins/security/users/op", json={"level": "viewer"})
    assert op.post("/mount/m/slew").status_code == 403


def test_duplicate_and_invalid_user(client):
    create_admin(client)
    assert client.post("/plugins/security/users", json={"name": "ROOT", "password": "password1"}).status_code == 409
    assert client.post("/plugins/security/users", json={"name": "a b", "password": "password1"}).status_code == 422
    assert client.post("/plugins/security/users", json={"name": "x", "password": "short"}).status_code == 422


# ── guest ────────────────────────────────────────────────────────────────────

def test_guest_is_read_only(client, app):
    create_admin(client)
    g = anon(app)
    assert g.get("/mount/m/status").status_code == 401
    client.put("/plugins/security/settings", json={"guest_enabled": True, "allowed_origins": []})
    s = g.get("/auth/status").json()
    assert s["authenticated"] and s["kind"] == "guest" and s["level"] == "viewer" and s["guest_allowed"]
    assert g.get("/mount/m/status").status_code == 200
    assert g.post("/mount/m/slew").status_code == 403
    assert g.post("/plugins/security/me/password",
                  json={"current_password": "x", "new_password": "password1"}).status_code == 403


def test_bad_token_is_not_downgraded_to_guest(client, app):
    create_admin(client)
    client.put("/plugins/security/settings", json={"guest_enabled": True, "allowed_origins": []})
    r = anon(app).get("/mount/m/status", headers={"Authorization": "Bearer astl_bogus"})
    assert r.status_code == 401


# ── tokens ───────────────────────────────────────────────────────────────────

def test_token_lifecycle(client, app):
    create_admin(client)
    r = client.post("/plugins/security/tokens", json={"name": "indi", "level": "operator"})
    assert r.status_code == 201
    secret, tid = r.json()["token"], r.json()["id"]
    assert secret.startswith("astl_")

    listed = client.get("/plugins/security/tokens").json()
    assert listed[0]["name"] == "indi" and "token" not in listed[0] and listed[0]["hint"] == secret[:9]

    bearer = {"Authorization": f"Bearer {secret}"}
    t = anon(app)
    assert t.post("/mount/m/slew", headers=bearer).status_code == 200
    assert t.put("/settings", headers=bearer).status_code == 403
    assert client.get("/plugins/security/tokens").json()[0]["last_used"] is not None

    assert client.delete(f"/plugins/security/tokens/{tid}").status_code == 204
    assert t.get("/mount/m/status", headers=bearer).status_code == 401


def test_token_secret_not_stored(client, tmp_path):
    create_admin(client)
    secret = client.post("/plugins/security/tokens", json={"name": "x", "level": "viewer"}).json()["token"]
    assert secret not in (tmp_path / "security.json").read_text()


def test_expired_token(client, app):
    create_admin(client)
    secret = client.post("/plugins/security/tokens", json={"name": "x", "level": "viewer", "expires_in_days": 1}).json()["token"]
    store = app.state.security.store
    store._data.tokens[0].expires = "2000-01-01T00:00:00+00:00"
    assert anon(app).get("/mount/m/status", headers={"Authorization": f"Bearer {secret}"}).status_code == 401


def test_service_token_loopback_only(client, app, tmp_path):
    create_admin(client)
    secret = (tmp_path / "service_token").read_text().strip()
    assert ((tmp_path / "service_token").stat().st_mode & 0o777) == 0o600
    bearer = {"Authorization": f"Bearer {secret}"}
    local = TestClient(app, base_url="http://astro.lan", client=("127.0.0.1", 5000))
    assert local.post("/mount/m/slew", headers=bearer).status_code == 200
    assert local.put("/settings", headers=bearer).status_code == 403  # operator, not admin
    assert local.post("/mount/m/slew", headers={**bearer, "X-Forwarded-For": "10.0.0.5"}).status_code == 401
    remote = TestClient(app, base_url="http://astro.lan", client=("10.0.0.5", 5000))
    assert remote.post("/mount/m/slew", headers=bearer).status_code == 401


# ── websocket ────────────────────────────────────────────────────────────────

def test_websocket_requires_login(client, app):
    create_admin(client)
    with pytest.raises(WebSocketDisconnect):
        with anon(app).websocket_connect("/ws/events"):
            pass
    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())  # the test client omits its jar here
    with client.websocket_connect("/ws/events", headers={"cookie": cookie}) as ws:
        assert ws.receive_json() == {"hi": 1}


# ── UI shell stays reachable ─────────────────────────────────────────────────

def test_ui_shell_and_health_public(client, app):
    create_admin(client)
    c = anon(app)
    assert c.get("/who").json() == {"principal": None}  # not an API path: reaches the handler
    assert c.get("/auth/status").status_code == 200


# ── origins ──────────────────────────────────────────────────────────────────

def test_allowed_origin_setting_applies_live_with_cors(client, app):
    create_admin(client)
    secret = client.post("/plugins/security/tokens", json={"name": "x", "level": "viewer"}).json()["token"]
    hdr = {"Authorization": f"Bearer {secret}", "Origin": "https://tool.example"}
    c = anon(app)
    assert c.get("/mount/m/status", headers=hdr).status_code == 403  # not allowed yet

    r = client.put("/plugins/security/settings",
                   json={"guest_enabled": False, "allowed_origins": ["https://tool.example/"]})
    assert r.json()["allowed_origins"] == ["https://tool.example"]
    r = c.get("/mount/m/status", headers=hdr)
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "https://tool.example"
    assert "access-control-allow-credentials" not in r.headers

    pre = c.options("/mount/m/slew", headers={"Origin": "https://tool.example", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 204 and "Authorization" in pre.headers["access-control-allow-headers"]


def test_bad_origin_setting_rejected(client):
    create_admin(client)
    r = client.put("/plugins/security/settings", json={"guest_enabled": False, "allowed_origins": ["not a url"]})
    assert r.status_code == 422


def test_cross_origin_cannot_use_session_cookie(client, app):
    create_admin(client)
    r = client.post("/mount/m/slew", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


# ── plumbing ─────────────────────────────────────────────────────────────────

def test_acl_defaults():
    from astrolol.core.auth import default_acl
    acl = default_acl()
    assert acl.lookup("GET", "/mount/x/status") == (False, Level.VIEWER)
    assert acl.lookup("POST", "/mount/x/slew") == (False, Level.OPERATOR)
    assert acl.lookup("POST", "/profiles/p1/activate") == (False, Level.OPERATOR)
    assert acl.lookup("PUT", "/profiles/p1") == (False, Level.ADMIN)
    assert acl.lookup("DELETE", "/profiles/active") == (False, Level.OPERATOR)
    assert acl.lookup("POST", "/devices/connect") == (False, Level.ADMIN)
    assert acl.lookup("POST", "/devices/connected/c1/disconnect") == (False, Level.OPERATOR)
    assert acl.lookup("POST", "/admin/restart") == (False, Level.ADMIN)
    assert acl.lookup("GET", "/health")[0] is True


def test_plugin_settings_hidden_from_non_admins(client, app, tmp_path):
    from astrolol.api.settings import router as settings_router
    app.include_router(settings_router)
    app.state.profile_store = app.state.plugin_ctx.profile_store
    store = app.state.plugin_ctx.profile_store
    cur = store.get_user_settings()
    store.update_user_settings(cur.model_copy(update={"plugin_settings": {"system": {"hotspot_password": "pw"}}}))

    create_admin(client)
    _user(client, "view", "viewer")
    assert client.get("/settings").json()["plugin_settings"]["system"]["hotspot_password"] == "pw"
    assert login(anon(app), "view", "password1").get("/settings").json()["plugin_settings"] == {}


def test_recovery_cli(client, tmp_path, monkeypatch, capsys):
    from astrolol.plugins.security import __main__ as cli

    create_admin(client)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: "brand new pass")
    cli.main(["add-admin", "rescue"])
    cli.main(["list"])
    assert "rescue\tadmin" in capsys.readouterr().out
    cli.main(["reset"])
    from astrolol.plugins.security.store import SecurityStore
    assert not SecurityStore(tmp_path / "security.json").has_users()


def test_double_star_covers_the_prefix_itself():
    from astrolol.core.auth import default_acl
    acl = default_acl()
    assert acl.lookup("POST", "/inventory") == (False, Level.ADMIN)
    assert acl.lookup("POST", "/inventory/x/y") == (False, Level.ADMIN)
    assert acl.lookup("POST", "/inventoryx") == (False, Level.OPERATOR)
