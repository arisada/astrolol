"""
End-to-end API tests against an INDIGO server: HTTP → FastAPI → INDI adapters → indigo_server.

Two set-ups, as a user would have them (Settings.indi_server_kind = "indigo"):

  - Unmanaged: an INDIGO server is already running (here started by the tests with no
    drivers, so it lists them all); astrolol loads drivers into it through its "Server" device.
  - Managed: astrolol starts indigo_server itself on the first device and stops it from
    POST /admin/indi/stop.

Skipped automatically when indigo_server is not installed.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.indi_server import start_indigo_server as _start_indigo_server
from tests.indi_server import stop_indiserver as _stop

pytestmark = pytest.mark.skipif(
    shutil.which("indigo_server") is None,
    reason="indigo_server not installed",
)

_UNMANAGED_PORT = 17850
_MANAGED_PORT = 17851


def _make_app(monkeypatch: pytest.MonkeyPatch, *, port: int, manage: bool, images_dir: Path):
    """An app talking to an INDIGO server on *port*; settings are read when it is built."""
    from astrolol.config.settings import settings
    from astrolol.main import create_app

    monkeypatch.setattr(settings, "indi_server_kind", "indigo")
    monkeypatch.setattr(settings, "indi_manage_server", manage)
    monkeypatch.setattr(settings, "indi_port", port)
    monkeypatch.setattr(settings, "images_dir", images_dir)
    return create_app()


def _client(app) -> AsyncClient:  # noqa: ANN001
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60.0)


def _driver_loaded(app, driver: str) -> bool:  # noqa: ANN001
    client = app.state.registry.indi_manager.client
    return bool(client.get_switch_state_nowait("Server", "DRIVERS", driver))


# ---------------------------------------------------------------------------
# Unmanaged: a running INDIGO server
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def unmanaged_app(tmp_path_factory):
    proc = _start_indigo_server(_UNMANAGED_PORT)   # no drivers: astrolol loads them
    with pytest.MonkeyPatch.context() as mp:
        yield _make_app(
            mp, port=_UNMANAGED_PORT, manage=False,
            images_dir=tmp_path_factory.mktemp("indigo_api_images"),
        )
    _stop(proc)


async def test_catalog_lists_indigo_drivers(unmanaged_app):
    async with _client(unmanaged_app) as c:
        r = await c.get("/indi/drivers/camera")
    assert r.status_code == 200
    by_driver = {d["executable"]: d for d in r.json()}
    assert by_driver["indigo_ccd_simulator"]["manufacturer"] == "Simulator"
    assert all(d["kind"] == "camera" for d in r.json())
    assert not any(e.startswith("indi_") for e in by_driver)


async def test_load_driver_finds_the_driver_devices(unmanaged_app):
    async with _client(unmanaged_app) as c:
        r = await c.post("/indi/load_driver", json={
            "executable": "indigo_ccd_simulator", "device_name": "Camera Simulator",
        })
    assert r.status_code == 200, r.text
    names = r.json()["device_names"]
    assert names[0] == "CCD Imager Simulator"
    assert "CCD Imager Simulator (wheel)" in names
    assert not any(n.endswith("(guider)") or n.endswith("(AO)") for n in names)
    assert any(p["name"] == "CONNECTION" for p in r.json()["properties"])


async def test_load_driver_for_a_mount(unmanaged_app):
    async with _client(unmanaged_app) as c:
        r = await c.post("/indi/load_driver", json={
            "executable": "indigo_mount_simulator", "device_name": "Mount Simulator",
        })
    assert r.status_code == 200, r.text
    assert r.json()["device_names"] == ["Mount Simulator"]


async def test_load_driver_refuses_an_indi_driver(unmanaged_app):
    async with _client(unmanaged_app) as c:
        r = await c.post("/indi/load_driver", json={
            "executable": "indi_simulator_ccd", "device_name": "CCD Simulator",
        })
    assert r.status_code == 502
    assert "INDIGO" in r.json()["detail"]


async def test_camera_brings_its_wheel_and_focuser_and_unloads_with_them(unmanaged_app):
    async with _client(unmanaged_app) as c:
        r = await c.post("/devices/connect", json={
            "device_id": "indigo_cam",
            "kind": "camera",
            "adapter_key": "indi_camera",
            "params": {"device_name": "CCD Imager Simulator", "executable": "indigo_ccd_simulator"},
        })
        assert r.status_code == 201, r.text
        connected = {d["device_id"]: d for d in (await c.get("/devices/connected")).json()}
        companions = [connected[i] for i in connected["indigo_cam"]["companions"]]
        assert sorted((d["kind"], d["driver_name"]) for d in companions) == [
            ("filter_wheel", "CCD Imager Simulator (wheel)"),
            ("focuser", "CCD Imager Simulator (focuser)"),
        ]
        assert all(d["state"] == "connected" for d in companions)

        r = await c.post("/imager/indigo_cam/expose", json={"duration": 0.2})
        assert r.status_code == 201, r.text
        assert Path(r.json()["fits_path"]).stat().st_size > 0

        r = await c.delete("/devices/connected/indigo_cam")
        assert r.status_code == 204
        assert (await c.get("/devices/connected")).json() == []
    # The camera and both companions used the driver; it went with the last of them.
    for _ in range(20):
        if not _driver_loaded(unmanaged_app, "indigo_ccd_simulator"):
            break
        await asyncio.sleep(0.25)
    assert not _driver_loaded(unmanaged_app, "indigo_ccd_simulator")


# ---------------------------------------------------------------------------
# Managed: astrolol starts and stops indigo_server
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def managed_app(tmp_path_factory):
    home = tmp_path_factory.mktemp("indigo_home")
    run_dir = tmp_path_factory.mktemp("indigo_run")
    with pytest.MonkeyPatch.context() as mp:
        # indigo_server keeps its state in $HOME/.indigo: never the developer's.
        mp.setenv("HOME", str(home))
        app = _make_app(
            mp, port=_MANAGED_PORT, manage=True,
            images_dir=tmp_path_factory.mktemp("indigo_managed_images"),
        )
        server = app.state.registry.indi_manager._server
        # The state file goes to the app's run dir (/tmp/astrolol by default): keep it apart.
        server._run_dir, server._state_path = run_dir, run_dir / "astrolol_indigo.json"
        yield app
        if server.is_running:
            asyncio.run(server.stop())


async def test_managed_server_starts_runs_a_mount_and_stops(managed_app):
    server = managed_app.state.registry.indi_manager._server
    async with _client(managed_app) as c:
        r = await c.post("/devices/connect", json={
            "device_id": "indigo_mount",
            "kind": "mount",
            "adapter_key": "indi_mount",
            "params": {"device_name": "Mount Simulator", "executable": "indigo_mount_simulator"},
        })
        assert r.status_code == 201, r.text
        assert server.is_running
        r = await c.get("/mount/indigo_mount/status")
        assert r.status_code == 200, r.text
        assert r.json()["ra"] is not None

        r = await c.delete("/devices/connected/indigo_mount")
        assert r.status_code == 204
        r = await c.post("/admin/indi/stop")
        assert r.status_code == 202, r.text
    for _ in range(50):
        if not server.is_running:
            break
        await asyncio.sleep(0.1)
    assert not server.is_running
