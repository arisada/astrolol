"""The MCP endpoint: protocol, tools against a stand-in API, and access control."""
from __future__ import annotations

import base64
import io
import json

from fastapi.testclient import TestClient

from astrolol.plugins.mcp.tests.conftest import Mcp, make_app
from astrolol.plugins.mcp.tools import REGISTRY

# ── protocol ──────────────────────────────────────────────────────────────────

def test_initialize_negotiates_version_and_announces_tools(mcp: Mcp) -> None:
    out = mcp.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "t", "version": "1"}})["result"]
    assert out["protocolVersion"] == "2025-06-18"
    assert out["capabilities"]["tools"] == {"listChanged": False}
    assert out["serverInfo"] == {"name": "astrolol", "version": "9.9.9"}
    assert "get_overview" in out["instructions"]


def test_unknown_protocol_version_falls_back_to_one_we_speak(mcp: Mcp) -> None:
    out = mcp.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert out["protocolVersion"] == "2025-06-18"


def test_notifications_get_202_and_no_body(mcp: Mcp) -> None:
    r = mcp.client.post("/plugins/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""


def test_ping_unknown_method_and_bad_input(mcp: Mcp) -> None:
    assert mcp.rpc("ping")["result"] == {}
    assert mcp.rpc("resources/list")["error"]["code"] == -32601
    assert mcp.client.post("/plugins/mcp", content=b"{nope").json()["error"]["code"] == -32700
    assert mcp.client.post("/plugins/mcp", json={"hello": 1}).json()["error"]["code"] == -32600
    assert mcp.rpc("tools/call", {"name": "nope"})["error"]["code"] == -32602


def test_batch_returns_only_replies_to_requests(mcp: Mcp) -> None:
    r = mcp.client.post("/plugins/mcp", json=[
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ])
    assert [m["id"] for m in r.json()] == [1]


def test_trailing_slash_works_and_get_is_refused(mcp: Mcp) -> None:
    r = mcp.client.post("/plugins/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 200
    assert mcp.client.get("/plugins/mcp").status_code == 405
    assert mcp.client.delete("/plugins/mcp").status_code == 405


# ── tool catalogue ────────────────────────────────────────────────────────────

def test_every_tool_is_well_formed(mcp: Mcp) -> None:
    app = make_app(enabled={"sequencer", "autofocus", "platesolve", "guider", "target"})
    with TestClient(app) as c:
        tools = Mcp(c).rpc("tools/list")["result"]["tools"]
    assert len(tools) == len(REGISTRY.names())
    for t in tools:
        assert t["name"] and t["description"].endswith((".", ")", "?")), t["name"]
        schema = t["inputSchema"]
        assert schema["type"] == "object"
        assert set(schema.get("required", [])) <= set(schema["properties"]), t["name"]
        assert set(t["annotations"]) == {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
        assert not (t["annotations"]["readOnlyHint"] and t["annotations"]["destructiveHint"])
        json.dumps(t)  # serialisable


def test_tools_of_disabled_plugins_are_hidden(mcp: Mcp) -> None:
    names = {t["name"] for t in mcp.rpc("tools/list")["result"]["tools"]}
    assert {"get_overview", "mount_slew", "camera_expose", "emergency_stop"} <= names
    assert not {n for n in names if n.startswith(("sequencer_", "autofocus_", "guiding_", "platesolve_"))}
    result = mcp.call("sequencer_status")
    assert result["isError"] and "sequencer plugin" in mcp.text(result)


def test_obviously_dangerous_tools_are_flagged(mcp: Mcp) -> None:
    app = make_app(enabled={"sequencer", "platesolve"})
    with TestClient(app) as c:
        tools = {t["name"]: t["annotations"] for t in Mcp(c).rpc("tools/list")["result"]["tools"]}
    for name in ("mount_slew", "mount_sync", "mount_meridian_flip", "sequencer_start", "platesolve_center"):
        assert tools[name]["destructiveHint"], name
    for name in ("get_overview", "mount_status", "camera_status", "get_events", "api_get"):
        assert tools[name]["readOnlyHint"], name


# ── tools ─────────────────────────────────────────────────────────────────────

def test_overview_collects_device_status(mcp: Mcp) -> None:
    out = json.loads(mcp.text(mcp.call("get_overview")))
    assert out["active_profile"] == {"id": "p1", "name": "Backyard"}
    assert out["status"]["mount_sim"]["is_tracking"] is True
    assert out["status"]["focuser_sim"]["position"] == 5000
    assert out["status"]["camera_sim"]["state"] == "idle"


def test_slew_sets_target_and_waits_for_the_event(mcp: Mcp, app) -> None:
    result = mcp.call("mount_slew", device_id="mount_sim", ra_deg=83.8, dec_deg=-5.4, name="M42")
    assert not result["isError"], mcp.text(result)
    assert json.loads(mcp.text(result))["result"] == "arrived"
    assert [c for c in app.state.calls if c[0] != "GET"] == [
        ("PUT", "/mount/mount_sim/target"), ("POST", "/mount/mount_sim/slew")]


def test_slew_reports_an_aborted_slew_as_an_error(mcp: Mcp, app) -> None:
    app.state.slew_outcome = "aborted"
    result = mcp.call("mount_slew", device_id="mount_sim", ra_deg=1, dec_deg=2)
    assert result["isError"] and "aborted" in mcp.text(result)


def test_slew_times_out_with_the_state_it_found(mcp: Mcp, app) -> None:
    app.state.slew_outcome = "never"
    result = mcp.call("mount_slew", device_id="mount_sim", ra_deg=1, dec_deg=2, timeout_s=1)
    assert json.loads(mcp.text(result))["result"] == "timeout"


def test_slew_without_wait_returns_at_once(mcp: Mcp) -> None:
    result = mcp.call("mount_slew", device_id="mount_sim", wait=False)
    assert json.loads(mcp.text(result)) == {"result": "slewing"}


def test_half_a_coordinate_is_refused(mcp: Mcp, app) -> None:
    result = mcp.call("mount_slew", device_id="mount_sim", ra_deg=1)
    assert result["isError"] and "both" in mcp.text(result)
    assert not [c for c in app.state.calls if c[0] == "POST"]


def test_arguments_are_checked(mcp: Mcp) -> None:
    assert "Missing" in mcp.text(mcp.call("mount_status"))
    assert "Unknown argument" in mcp.text(mcp.call("mount_status", device_id="m", colour="red"))


def test_device_ids_cannot_escape_their_path(mcp: Mcp, app) -> None:
    for bad in ("../../admin/restart", "a/b", "..", "x?y", "a b", ""):
        result = mcp.call("mount_stop", device_id=bad)
        assert result["isError"] and "Invalid device_id" in mcp.text(result), bad
    assert not app.state.calls


def test_rest_errors_become_tool_errors_the_model_can_read(mcp: Mcp) -> None:
    result = mcp.call("camera_expose", device_id="camera_sim", duration_s=700)
    assert result["isError"] and "409" in mcp.text(result) and "Camera busy" in mcp.text(result)


def test_expose_returns_result_stats_and_a_shrunk_preview(mcp: Mcp) -> None:
    result = mcp.call("camera_expose", device_id="camera_sim", duration_s=2, preview_max_px=400)
    assert not result["isError"]
    info = json.loads(result["content"][0]["text"])
    assert info["result"]["fits_path"] == "/data/a.fits" and info["stats"] == {"median": 1200.0}
    image = result["content"][1]
    assert image["type"] == "image" and image["mimeType"] == "image/jpeg"
    from PIL import Image
    assert max(Image.open(io.BytesIO(base64.b64decode(image["data"]))).size) == 400


def test_expose_without_preview_has_no_image(mcp: Mcp) -> None:
    result = mcp.call("camera_expose", device_id="camera_sim", duration_s=1, include_preview=False)
    assert [c["type"] for c in result["content"]] == ["text"]


def test_events_are_filtered_and_trimmed(mcp: Mcp, app) -> None:
    mcp.call("mount_slew", device_id="mount_sim", ra_deg=1, dec_deg=2)
    events = json.loads(mcp.text(mcp.call("get_events", type_prefix="mount.slew")))
    assert [e["type"] for e in events] == ["mount.slew_completed"]
    assert "id" not in events[0]


def test_api_get_only_reads_and_stays_inside_the_api(mcp: Mcp) -> None:
    assert json.loads(mcp.text(mcp.call("api_get", path="/secret"))) == {"x": 1}
    for bad in ("secret", "/../x", "/auth/status", "/admin/log_scopes", "/a//b", "/x?y=1", "http://evil/"):
        assert mcp.call("api_get", path=bad)["isError"], bad


def test_emergency_stop_reaches_every_moving_device(mcp: Mcp, app) -> None:
    out = json.loads(mcp.text(mcp.call("emergency_stop")))
    assert out == {"mount_stop mount_sim": "ok", "camera_halt camera_sim": "ok", "focuser_halt focuser_sim": "ok"}
    assert {c for c in app.state.calls if c[0] == "POST"} == {
        ("POST", "/mount/mount_sim/stop"), ("POST", "/imager/camera_sim/halt"), ("POST", "/focuser/focuser_sim/halt")}


def test_a_crashing_tool_does_not_take_the_endpoint_down(mcp: Mcp, monkeypatch) -> None:
    async def boom(ctx, args):
        raise RuntimeError("kaput")

    monkeypatch.setattr(REGISTRY.get("list_devices"), "handler", boom)
    result = mcp.call("list_devices")
    assert result["isError"] and "kaput" in mcp.text(result)
    assert mcp.rpc("ping")["result"] == {}


# ── access control ────────────────────────────────────────────────────────────

def _client(token: str | None) -> Mcp:
    c = TestClient(make_app(secure=True))
    return Mcp(c, {"Authorization": f"Bearer {token}"} if token else {})


def test_without_credentials_the_endpoint_answers_401() -> None:
    r = _client(None).client.post("/plugins/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_a_viewer_can_look_but_not_touch() -> None:
    viewer = _client("viewer-token")
    assert viewer.rpc("ping")["result"] == {}
    assert not viewer.call("mount_status", device_id="mount_sim")["isError"]
    assert json.loads(viewer.text(viewer.call("get_overview")))["status"]["mount_sim"]
    for name, args in [("mount_stop", {"device_id": "mount_sim"}),
                       ("mount_slew", {"device_id": "mount_sim", "ra_deg": 1, "dec_deg": 2}),
                       ("camera_expose", {"device_id": "camera_sim", "duration_s": 1})]:
        result = viewer.call(name, **args)
        assert result["isError"] and "403" in viewer.text(result) and "operator" in viewer.text(result), name


def test_an_operator_can_operate() -> None:
    op = _client("operator-token")
    assert not op.call("mount_stop", device_id="mount_sim")["isError"]
    assert not op.call("mount_slew", device_id="mount_sim", ra_deg=1, dec_deg=2)["isError"]


def test_the_callers_credentials_are_not_shared_between_requests() -> None:
    app = make_app(secure=True)
    c = TestClient(app)
    viewer, op = Mcp(c, {"Authorization": "Bearer viewer-token"}), Mcp(c, {"Authorization": "Bearer operator-token"})
    assert not op.call("mount_stop", device_id="mount_sim")["isError"]
    assert viewer.call("mount_stop", device_id="mount_sim")["isError"]
    assert not op.call("mount_stop", device_id="mount_sim")["isError"]


def test_info_and_skill_pages(mcp: Mcp) -> None:
    info = mcp.client.get("/plugins/mcp/info").json()
    assert info["endpoint"].endswith("/plugins/mcp") and info["auth_required"] is False
    assert {"get_overview", "mount_slew"} <= {t["name"] for t in info["tools"]}
    skill = mcp.client.get("/plugins/mcp/skill").text
    assert skill.startswith("---\nname: astrolol-observing\n")


# ── the real application ──────────────────────────────────────────────────────

def test_real_app_viewer_cannot_operate_through_mcp(tmp_path, monkeypatch) -> None:
    """Whole stack: sign-in on, MCP enabled; a viewer's tool calls hit the real access rules."""
    from astrolol.config.settings import settings
    from astrolol.main import create_app
    from astrolol.profiles.store import ProfileStore

    for name in ("profiles_file", "inventory_file", "security_file", "service_token_file"):
        monkeypatch.setattr(settings, name, tmp_path / name)
    store = ProfileStore(settings.profiles_file)
    store.update_user_settings(store.get_user_settings().model_copy(update={"enabled_plugins": ["security", "mcp"]}))
    app = create_app()

    admin = TestClient(app)
    assert admin.post("/plugins/security/users", json={"name": "root", "password": "correct horse"}).status_code == 201
    assert admin.post("/plugins/security/users",
                      json={"name": "eye", "password": "password1", "level": "viewer"}).status_code == 201
    viewer = TestClient(app)
    assert viewer.post("/auth/login", json={"username": "eye", "password": "password1"}).status_code == 200
    anon = TestClient(app)

    assert anon.post("/plugins/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401

    v = Mcp(viewer)
    tools = {t["name"] for t in v.rpc("tools/list")["result"]["tools"]}
    assert {"get_overview", "mount_slew", "emergency_stop"} <= tools
    overview = v.call("get_overview")
    assert not overview["isError"] and json.loads(v.text(overview))["devices"] == []
    refused = v.call("mount_stop", device_id="mount_x")
    assert refused["isError"] and "403" in v.text(refused)

    a = Mcp(admin)
    missing = a.call("mount_stop", device_id="mount_x")  # allowed in, then the device does not exist
    assert missing["isError"] and "404" in a.text(missing)
