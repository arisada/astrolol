"""End-to-end API tests against OmniSim: HTTP → FastAPI → managers → Alpaca adapters → OmniSim.

The plugin is enabled as a user does in Options → Plugins; devices are connected as from the
Equipment page's "Other adapter" step: an ``alpaca_*`` adapter and its connect params (host,
port, device number). Skipped without OmniSim.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.mount.sky import local_sidereal_time_h
from tests.alpaca_sim import OmniSim


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # noqa: ANN201
    from astrolol.config.settings import settings
    from astrolol.main import create_app
    from astrolol.profiles.store import ProfileStore

    monkeypatch.setattr(settings, "images_dir", tmp_path / "images")
    monkeypatch.setattr(settings, "profiles_file", tmp_path / "profiles.json")
    monkeypatch.setattr(settings, "inventory_file", tmp_path / "inventory.json")
    store = ProfileStore(settings.profiles_file)
    store.update_user_settings(store.get_user_settings().model_copy(update={"enabled_plugins": ["alpaca"]}))
    return create_app()


def _client(app) -> AsyncClient:  # noqa: ANN001
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60.0)


async def _connect(c: AsyncClient, sim: OmniSim, kind: str, adapter: str, device_id: str) -> None:
    r = await c.post("/devices/connect", json={
        "device_id": device_id,
        "kind": kind,
        "adapter_key": adapter,
        "params": {"host": sim.host, "port": sim.port, "device_number": 0},
    })
    assert r.status_code == 201, r.text


async def test_alpaca_adapters_are_offered(app) -> None:  # noqa: ANN001
    assert "alpaca" in app.state.enabled_plugin_ids
    async with _client(app) as c:
        available = (await c.get("/devices/available")).json()
        assert "alpaca_camera" in available["cameras"]
        assert "alpaca_mount" in available["mounts"]
        r = await c.get("/devices/available/camera/alpaca_camera/defaults")
    assert r.status_code == 200
    assert set(r.json()) == {"host", "port", "device_number"}


async def test_camera_exposes_through_the_imager(app, omnisim) -> None:  # noqa: ANN001
    async with _client(app) as c:
        await _connect(c, omnisim, "camera", "alpaca_camera", "acam")
        r = await c.post("/imager/acam/expose", json={"duration": 0.5})
        assert r.status_code == 201, r.text
        result = r.json()
        assert (result["width"], result["height"]) == (800, 600)
        assert Path(result["fits_path"]).exists()
        assert Path(result["preview_path"]).exists()
        status = (await c.get("/imager/acam/camera_status")).json()
        assert status["state"] == "connected"
        assert (await c.delete("/devices/connected/acam")).status_code in (200, 204)


async def test_mount_slews_through_the_mount_api(app, omnisim) -> None:  # noqa: ANN001
    async with _client(app) as c:
        await _connect(c, omnisim, "mount", "alpaca_mount", "amount")
        status = (await c.get("/mount/amount/status")).json()
        if status["is_parked"]:
            assert (await c.post("/mount/amount/unpark")).status_code == 204
        lon = -0.29444   # OmniSim's site
        lst = local_sidereal_time_h(datetime.now(timezone.utc), lon)
        ra_deg = ((lst - 1.0) % 24) * 15
        r = await c.put("/mount/amount/target", json={"ra": ra_deg, "dec": 35.0})
        assert r.status_code == 200, r.text
        assert (await c.post("/mount/amount/slew")).status_code == 202
        for _ in range(120):
            await asyncio.sleep(0.5)
            status = (await c.get("/mount/amount/status")).json()
            if not status["is_slewing"] and abs(status["dec"] - 35.0) < 0.05:
                break
        else:
            pytest.fail(f"slew did not finish: {status}")
        assert abs(((status["ra"] * 15 - ra_deg + 180) % 360) - 180) < 0.05
        r = await c.post("/mount/amount/pulse_guide", json={"direction": "N", "duration_ms": 200})
        assert r.status_code == 204, r.text
        r = await c.post("/mount/amount/move", json={"direction": "E", "rate": "16x", "duration_ms": 300})
        assert r.status_code == 204, r.text
        await c.delete("/devices/connected/amount")


async def test_focuser_and_filter_wheel_through_their_apis(app, omnisim) -> None:  # noqa: ANN001
    async with _client(app) as c:
        await _connect(c, omnisim, "focuser", "alpaca_focuser", "afoc")
        await _connect(c, omnisim, "filter_wheel", "alpaca_filter_wheel", "awheel")
        assert (await c.post("/focuser/afoc/move_to", json={"position": 21000})).status_code == 202
        for _ in range(60):
            await asyncio.sleep(0.25)
            status = (await c.get("/focuser/afoc/status")).json()
            if status["position"] == 21000 and not status["is_moving"]:
                break
        else:
            pytest.fail(f"focuser did not arrive: {status}")
        assert (await c.post("/filter_wheel/awheel/select", json={"slot": 2})).status_code == 204
        status = (await c.get("/filter_wheel/awheel/status")).json()
        assert status["current_slot"] == 2 and status["filter_names"][1] == "Green"
        await c.delete("/devices/connected/afoc")
        await c.delete("/devices/connected/awheel")


async def test_adapters_need_the_plugin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from astrolol.config.settings import settings
    from astrolol.main import create_app

    monkeypatch.setattr(settings, "profiles_file", tmp_path / "profiles.json")
    app = create_app()
    async with _client(app) as c:
        available = (await c.get("/devices/available")).json()
    assert not any(k.startswith("alpaca_") for keys in available.values() for k in keys)
