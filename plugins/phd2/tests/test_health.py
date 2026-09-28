"""Guiding health tracking and the client's settle-waiting guide()."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from plugins.phd2.api import router
from plugins.phd2.client import Phd2Client
from plugins.phd2.health import GuidingHealthTracker


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_starts_unguided() -> None:
    clock = Clock()
    h = GuidingHealthTracker(clock)
    clock.t += 30
    health = h.health()
    assert not health.guiding
    assert health.unguided_for_s == 30
    assert health.reason == "not_guiding"


def test_short_loss_mid_window() -> None:
    clock = Clock()
    h = GuidingHealthTracker(clock)
    h.on_step(0.0, 0.0)  # guiding from t=1000
    clock.t += 1
    start = h.mark()  # t=1001
    for _ in range(5):
        clock.t += 2
        h.on_step(0.3, -0.4)
    h.on_lost("star_lost")  # t=1011
    h.on_lost("star_lost")  # repeated StarLost events: same gap
    clock.t += 10
    h.on_step(0.3, 0.4)  # recovered at t=1021
    clock.t += 5
    stats = h.stats(start)
    assert stats.duration_s == 25
    assert stats.unguided_s == 10
    assert stats.losses == 1
    assert stats.steps == 6
    assert stats.rms_ra == pytest.approx(0.3)
    assert stats.rms_total == pytest.approx(0.5)
    health = h.health()
    assert health.guiding and health.guiding_for_s == 5


def test_window_clips_gaps() -> None:
    clock = Clock()
    h = GuidingHealthTracker(clock)
    h.on_step(0.0, 0.0)
    clock.t += 10
    h.on_lost("stopped")  # 1010 → still open
    clock.t += 100  # now 1110
    stats = h.stats(1050.0)
    assert stats.unguided_s == 60
    assert stats.losses == 0  # the loss started before the window
    assert h.stats(1000.0).losses == 1


def test_never_guided_window_is_fully_unguided() -> None:
    clock = Clock()
    h = GuidingHealthTracker(clock)
    start = h.mark()
    clock.t += 42
    stats = h.stats(start)
    assert stats.unguided_s == 42
    assert stats.losses == 0  # it never was guiding: nothing was lost
    assert stats.rms_total is None


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
