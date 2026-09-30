"""PHD2 client: guiding health wiring, settle-waiting guide(), the Guider adapter."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from astrolol.core.guiding import Guider, GuiderNotConnected, SettleFailed, SettleParams
from plugins.phd2.api import router
from plugins.phd2.client import Phd2Client
from plugins.phd2.guider import Phd2Guider

# ── Client wiring ─────────────────────────────────────────────────────────────


def _client() -> Phd2Client:
    c = Phd2Client(host="localhost", port=4400, event_bus=EventBus())
    c._connected = True
    c._pixel_scale = 2.0
    return c


async def test_client_events_feed_health() -> None:
    c = _client()
    await c._handle_event({"Event": "GuideStep", "RADistanceRaw": 0.2, "DECDistanceRaw": 0.1})
    assert c.guiding_health().guiding
    await c._handle_event({"Event": "StarLost"})
    health = c.guiding_health()
    assert not health.guiding and health.reason == "star_lost"
    await c._handle_event({"Event": "GuideStep", "RADistanceRaw": 0.2, "DECDistanceRaw": 0.1})
    await c._handle_event({"Event": "AppState", "State": "Looping"})
    assert c.guiding_health().reason == "looping"
    stats = c.guiding_stats(0.0)
    assert stats.losses == 2
    assert stats.rms_ra == pytest.approx(0.4)  # arcsec: 0.2 px × 2″/px


async def test_disconnect_counts_as_loss() -> None:
    c = _client()
    await c._handle_event({"Event": "GuideStep", "RADistanceRaw": 0.0, "DECDistanceRaw": 0.0})
    c._on_disconnect()
    await asyncio.sleep(0)
    assert c.guiding_health().reason == "disconnected"


async def test_star_lost_notifies() -> None:
    from astrolol.core.guiding.events import GuidingStateChanged

    c = _client()
    q = c._event_bus.subscribe()
    await c._handle_event({"Event": "GuideStep", "RADistanceRaw": 0.0, "DECDistanceRaw": 0.0})
    while not q.empty():
        q.get_nowait()

    await c._handle_event({"Event": "StarLost"})

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    lost = next(e for e in events if isinstance(e, GuidingStateChanged))
    assert lost.notify == "warning"
    assert lost.notify_title
    assert lost.notify_body


async def _settling_client(error: str | None) -> tuple[Phd2Client, list[Any]]:
    c = _client()
    calls: list[Any] = []

    async def fake_call(method: str, params: Any = None) -> Any:
        calls.append((method, params))
        # PHD2 answers, then later announces the end of settling
        asyncio.get_running_loop().call_later(
            0.01,
            lambda: asyncio.ensure_future(
                c._handle_event({"Event": "SettleDone", "Error": error or ""})
            ),
        )
        return 0

    c._call = fake_call  # type: ignore[method-assign]
    return c, calls


async def test_guide_waits_for_settle() -> None:
    c, calls = await _settling_client(None)
    await c.guide(settle_pixels=1.0, settle_time=5, settle_timeout=30, wait_settle=True)
    assert calls[0][0] == "guide"
    assert c._settle_event is None


async def test_guide_settle_failure_raises() -> None:
    c, _ = await _settling_client("timed-out waiting for guider to settle")
    with pytest.raises(RuntimeError, match="settle failed"):
        await c.guide(wait_settle=True)


async def test_guide_without_wait_returns_immediately() -> None:
    c, calls = await _settling_client(None)
    await c.guide()
    assert calls[0][0] == "guide"


async def test_dither_still_settles() -> None:
    c, calls = await _settling_client(None)
    await c.dither(pixels=3.0)
    assert calls[0][0] == "dither"
    assert not c._dithering


def test_health_route() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.phd2_client = _client()
    body = TestClient(app).get("/plugins/phd2/health?window_s=30").json()
    assert body["health"]["guiding"] is False
    assert body["window"]["losses"] == 0


# ── Guider adapter ────────────────────────────────────────────────────────────


async def test_adapter_implements_the_protocol_and_maps_errors() -> None:
    c, calls = await _settling_client("timed out")
    g = Phd2Guider(c)
    assert isinstance(g, Guider)
    with pytest.raises(SettleFailed):
        await g.guide(SettleParams(), wait_settle=True)
    c._connected = False
    with pytest.raises(GuiderNotConnected):
        await g.dither(3.0, False, SettleParams())
    await g.stop()  # not connected: no-op
    assert g.status().connected is False and g.status().active is False


async def test_adapter_status_and_generic_events() -> None:
    c = _client()
    q = c._event_bus.subscribe()
    g = Phd2Guider(c)
    c._state = "Guiding"
    await c._handle_event({"Event": "GuideStep", "RADistanceRaw": 0.1, "DECDistanceRaw": 0.1})
    st = g.status()
    assert st.guiding and st.active and st.pixel_scale == 2.0
    await c._handle_event({"Event": "StarLost"})
    types = []
    while not q.empty():
        types.append(q.get_nowait())
    changes = [e for e in types if getattr(e, "type", "") == "guiding.state_changed"]
    assert [(e.guiding, e.reason) for e in changes] == [(True, None), (False, "star_lost")]
