"""GuidingHealthTracker: guiding health and per-window statistics."""

from __future__ import annotations

import pytest

from astrolol.core.guiding.health import GuidingHealthTracker


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
