"""GuideSimulator behaviour (time_scale ≪ 1 so simulated seconds pass in milliseconds)."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator

import pytest

from astrolol.core.events import EventBus, MountSlewStarted
from astrolol.core.guiding import (
    Guider,
    GuiderError,
    GuiderNotConnected,
    SettleFailed,
    SettleParams,
)
from plugins.guide_simulator.settings import GuideSimSettings
from plugins.guide_simulator.simulator import GuideSimulator

FAST = GuideSimSettings(time_scale=0.01, step_interval_s=2.0, settle_extra_s=3.0, rms_arcsec=0.8)
SETTLE = SettleParams(pixels=1.5, time=5, timeout=60)


@pytest.fixture
async def sim() -> AsyncIterator[GuideSimulator]:
    s = GuideSimulator(EventBus(), FAST.model_copy(), rng=random.Random(1))
    await s.start()
    yield s
    await s.shutdown()


async def wait_until(cond, timeout: float = 3.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "condition not met"
        await asyncio.sleep(0.005)


async def test_implements_the_protocol(sim: GuideSimulator) -> None:
    assert isinstance(sim, Guider)


async def test_guide_settles_then_produces_steps(sim: GuideSimulator) -> None:
    t0 = time.monotonic()
    await sim.guide(SETTLE, wait_settle=True)
    assert time.monotonic() - t0 >= 0.08  # (5 + 3) × 0.01 s
    status = sim.status()
    assert status.guiding and status.active and status.state == "Guiding"
    mark = sim.mark()
    await asyncio.sleep(0.3)
    stats = sim.stats(mark)
    assert stats.steps >= 5
    assert stats.unguided_s == 0
    assert 0.2 < (stats.rms_total or 0) < 2.5


async def test_star_loss_recovers_by_itself(sim: GuideSimulator) -> None:
    await sim.guide(SETTLE)
    mark = sim.mark()
    await sim.lose_star(0.2)
    health = sim.health()
    assert not health.guiding and health.reason == "star_lost"
    assert sim.status().active  # still trying
    await wait_until(lambda: sim.health().guiding)
    stats = sim.stats(mark)
    assert stats.losses == 1
    assert 0.15 <= stats.unguided_s <= 0.5


async def test_guiding_stop_fault_needs_a_new_guide(sim: GuideSimulator) -> None:
    await sim.guide(SETTLE)
    await sim.stop_guiding_fault()
    await asyncio.sleep(0.1)
    assert not sim.status().active and not sim.health().guiding
    await sim.guide(SETTLE)
    assert sim.health().guiding


async def test_settle_failures(sim: GuideSimulator) -> None:
    sim.fail_settles(1)
    with pytest.raises(SettleFailed):
        await sim.guide(SettleParams(time=1, timeout=5))
    await sim.guide(SettleParams(time=1, timeout=5))  # the next one works


async def test_settle_waits_for_a_lost_star_or_times_out(sim: GuideSimulator) -> None:
    await sim.guide(SETTLE)
    await sim.lose_star(None)
    with pytest.raises(SettleFailed, match="timed-out"):
        await sim.dither(3.0, False, SettleParams(time=1, timeout=10))
    sim.clear_faults()
    await sim.dither(3.0, False, SettleParams(time=1, timeout=10))


async def test_dither_needs_guiding(sim: GuideSimulator) -> None:
    with pytest.raises(GuiderError):
        await sim.dither(3.0, False, SETTLE)


async def test_disconnect(sim: GuideSimulator) -> None:
    await sim.guide(SETTLE)
    await sim.disconnect()
    assert sim.health().reason == "disconnected"
    with pytest.raises(GuiderNotConnected):
        await sim.guide(SETTLE)
    sim.connect()
    await sim.guide(SETTLE)


async def test_slewing_while_guiding_loses_the_star(sim: GuideSimulator) -> None:
    await sim.guide(SETTLE)
    await sim._bus.publish(MountSlewStarted(device_id="m1", ra=10.0, dec=20.0))
    await wait_until(lambda: not sim.status().active)
    assert sim.health().reason == "star_lost"


async def test_stop_is_not_a_loss_of_a_star(sim: GuideSimulator) -> None:
    await sim.guide(SETTLE)
    mark = sim.mark()
    await sim.stop()
    assert sim.health().reason == "stopped"
    assert sim.stats(mark).losses == 1
    await sim.stop()  # idempotent
