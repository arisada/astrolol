"""Tests for the PHD2 plugin API."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.phd2.api import router
from plugins.phd2.models import Phd2Status
from plugins.phd2.plugin import get_plugin


# ── Fake client ───────────────────────────────────────────────────────────────

class FakePhd2Client:
    """Controllable stand-in for Phd2Client."""

    def __init__(self) -> None:
        self._connected = True
        self._state = "Guiding"
        self.calls: list[tuple[str, dict]] = []
        self._raise: Exception | None = None

    def _maybe_raise(self) -> None:
        if self._raise:
            exc = self._raise
            self._raise = None
            raise exc

    def get_status(self) -> Phd2Status:
        return Phd2Status(
            connected=self._connected,
            state=self._state,
            rms_ra=0.25,
            rms_dec=0.18,
            rms_total=0.31,
            pixel_scale=1.5,
            star_snr=42.0,
            is_dithering=False,
            debug_enabled=False,
        )

    async def guide(self, **kwargs: object) -> None:
        self._maybe_raise()
        self.calls.append(("guide", kwargs))

    async def stop_capture(self) -> None:
        self._maybe_raise()
        self.calls.append(("stop_capture", {}))

    async def dither(self, **kwargs: object) -> None:
        self._maybe_raise()
        self.calls.append(("dither", kwargs))

    async def pause(self) -> None:
        self._maybe_raise()
        self.calls.append(("pause", {}))

    async def resume(self) -> None:
        self._maybe_raise()
        self.calls.append(("resume", {}))

    def set_debug(self, enabled: bool) -> None:
        self.calls.append(("set_debug", {"enabled": enabled}))


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.state.phd2_client = FakePhd2Client()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def fake(client: TestClient) -> FakePhd2Client:
    return client.app.state.phd2_client  # type: ignore[attr-defined]


# ── Status ────────────────────────────────────────────────────────────────────

def test_status_returns_200(client: TestClient) -> None:
    r = client.get("/phd2/status")
    assert r.status_code == 200
    data = r.json()
    assert data["connected"] is True
    assert data["state"] == "Guiding"
    assert data["rms_ra"] == 0.25
    assert data["rms_dec"] == 0.18
    assert data["rms_total"] == 0.31
    assert data["pixel_scale"] == 1.5
    assert data["star_snr"] == 42.0


def test_status_disconnected(client: TestClient, fake: FakePhd2Client) -> None:
    fake._connected = False
    fake._state = "Disconnected"
    r = client.get("/phd2/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False


# ── Guide ─────────────────────────────────────────────────────────────────────

def test_guide_default_body(client: TestClient, fake: FakePhd2Client) -> None:
    r = client.post("/phd2/guide", json={})
    assert r.status_code == 204
    assert fake.calls[-1][0] == "guide"


def test_guide_custom_settle(client: TestClient, fake: FakePhd2Client) -> None:
    body = {"settle": {"pixels": 2.0, "time": 15, "timeout": 90}, "recalibrate": True}
    r = client.post("/phd2/guide", json=body)
    assert r.status_code == 204
    method, kwargs = fake.calls[-1]
    assert method == "guide"
    assert kwargs["settle_pixels"] == 2.0
    assert kwargs["settle_time"] == 15
    assert kwargs["settle_timeout"] == 90
    assert kwargs["recalibrate"] is True


def test_guide_connection_error_returns_503(client: TestClient, fake: FakePhd2Client) -> None:
    fake._raise = ConnectionError("Not connected")
    r = client.post("/phd2/guide", json={})
    assert r.status_code == 503


def test_guide_generic_error_returns_502(client: TestClient, fake: FakePhd2Client) -> None:
    fake._raise = RuntimeError("PHD2 fault")
    r = client.post("/phd2/guide", json={})
    assert r.status_code == 502


# ── Stop ──────────────────────────────────────────────────────────────────────

def test_stop_returns_204(client: TestClient, fake: FakePhd2Client) -> None:
    r = client.post("/phd2/stop")
    assert r.status_code == 204
    assert fake.calls[-1][0] == "stop_capture"


def test_stop_connection_error_returns_503(client: TestClient, fake: FakePhd2Client) -> None:
    fake._raise = ConnectionError("gone")
    r = client.post("/phd2/stop")
    assert r.status_code == 503


# ── Dither ────────────────────────────────────────────────────────────────────

def test_dither_default_body(client: TestClient, fake: FakePhd2Client) -> None:
    r = client.post("/phd2/dither", json={})
    assert r.status_code == 204
    method, kwargs = fake.calls[-1]
    assert method == "dither"
    assert kwargs["pixels"] == 5.0
    assert kwargs["ra_only"] is False


def test_dither_custom(client: TestClient, fake: FakePhd2Client) -> None:
    body = {"pixels": 10.0, "ra_only": True, "settle": {"pixels": 3.0, "time": 5, "timeout": 30}}
    r = client.post("/phd2/dither", json=body)
    assert r.status_code == 204
    method, kwargs = fake.calls[-1]
    assert kwargs["pixels"] == 10.0
    assert kwargs["ra_only"] is True
    assert kwargs["settle_pixels"] == 3.0


def test_dither_timeout_returns_504(client: TestClient, fake: FakePhd2Client) -> None:
    fake._raise = TimeoutError("settle timed out")
    r = client.post("/phd2/dither", json={})
    assert r.status_code == 504


def test_dither_connection_error_returns_503(client: TestClient, fake: FakePhd2Client) -> None:
    fake._raise = ConnectionError("not connected")
    r = client.post("/phd2/dither", json={})
    assert r.status_code == 503


# ── Pause / Resume ────────────────────────────────────────────────────────────

def test_pause_returns_204(client: TestClient, fake: FakePhd2Client) -> None:
    r = client.post("/phd2/pause")
    assert r.status_code == 204
    assert fake.calls[-1][0] == "pause"


def test_resume_returns_204(client: TestClient, fake: FakePhd2Client) -> None:
    r = client.post("/phd2/resume")
    assert r.status_code == 204
    assert fake.calls[-1][0] == "resume"


def test_pause_connection_error_returns_503(client: TestClient, fake: FakePhd2Client) -> None:
    fake._raise = ConnectionError("gone")
    r = client.post("/phd2/pause")
    assert r.status_code == 503


def test_resume_connection_error_returns_503(client: TestClient, fake: FakePhd2Client) -> None:
    fake._raise = ConnectionError("gone")
    r = client.post("/phd2/resume")
    assert r.status_code == 503


# ── Debug ─────────────────────────────────────────────────────────────────────

def test_debug_enable(client: TestClient, fake: FakePhd2Client) -> None:
    r = client.post("/phd2/debug", json={"enabled": True})
    assert r.status_code == 204
    assert fake.calls[-1] == ("set_debug", {"enabled": True})


def test_debug_disable(client: TestClient, fake: FakePhd2Client) -> None:
    r = client.post("/phd2/debug", json={"enabled": False})
    assert r.status_code == 204
    assert fake.calls[-1] == ("set_debug", {"enabled": False})


# ── Plugin manifest ───────────────────────────────────────────────────────────

def test_plugin_manifest() -> None:
    plugin = get_plugin()
    assert plugin.manifest.id == "phd2"
    assert plugin.manifest.name == "PHD2 Guiding"
    assert plugin.manifest.version == "0.1.0"
