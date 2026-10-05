"""Tests for the flat wizard trial-and-error exposure solver."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrolol.core.events import EventBus
from astrolol.core.events.models import ImageStats
from astrolol.imaging.models import ExposureRequest
from plugins.flat_wizard.engine import FlatWizardEngine, _round_significant
from plugins.flat_wizard.models import FlatWizardConfig, FlatWizardFilterSpec, FlatWizardRun

FULL_SCALE = 65535.0


def _stats(mean: float) -> ImageStats:
    return ImageStats(
        histogram=[], hist_min=0, hist_max=FULL_SCALE, stretch_low=0, stretch_high=0,
        mean=mean, median=mean,
    )


class LinearFakeImager:
    """A flat's mean ADU response is linear in exposure duration: mean = duration * gain,
    clipped at the sensor's full-scale ADU once the frame is actually saturated."""

    def __init__(self, gain_per_second: float) -> None:
        self.gain_per_second = gain_per_second
        self.exposures: list[ExposureRequest] = []
        self._last_mean = 0.0

    async def expose(self, camera_id: str, request: ExposureRequest) -> None:
        self.exposures.append(request)
        self._last_mean = min(request.duration * self.gain_per_second, FULL_SCALE)

    def get_last_stats(self, camera_id: str) -> ImageStats:
        return _stats(self._last_mean)


def _make_app(imager: object, filter_wheel: object | None = None) -> SimpleNamespace:
    state = SimpleNamespace(imager_manager=imager)
    if filter_wheel is not None:
        state.filter_wheel_manager = filter_wheel
    return SimpleNamespace(state=state)


def _engine(app: SimpleNamespace) -> FlatWizardEngine:
    return FlatWizardEngine(app=app, event_bus=EventBus())


# ── Rounding ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value, expected",
    [
        (10.123456, 10.1),
        (0.00012345, 0.000123),
        (4.325310, 4.33),
        (0.5, 0.5),
        (0.0, 0.0),
        (100.0, 100.0),
    ],
)
def test_round_significant(value: float, expected: float) -> None:
    assert _round_significant(value) == expected


# ── Convergence ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_solve_filter_converges_on_target_ratio() -> None:
    """With an exactly-linear response, the first proportional correction after the
    seed trial should land within tolerance."""
    imager = LinearFakeImager(gain_per_second=10_000.0)
    config = FlatWizardConfig(
        camera_id="cam_1", filters=[FlatWizardFilterSpec(count=10)], seed_duration=0.5,
    )
    run = FlatWizardRun(config=config, total_filters=1)
    engine = _engine(_make_app(imager))

    result = await engine._solve_filter(run, config.filters[0], 0)

    assert result.status == "solved"
    assert result.solved_duration is not None
    expected = (config.target_pct / 100.0) * FULL_SCALE / imager.gain_per_second
    assert result.solved_duration == _round_significant(expected)
    assert len(result.trials) <= 2


@pytest.mark.asyncio
async def test_solve_filter_backs_off_from_saturation() -> None:
    """A seed duration that clips the sensor must not be scaled proportionally
    (the clipped mean under-predicts the real overexposure) — it should instead
    be halved until no longer saturated, then converge normally."""
    imager = LinearFakeImager(gain_per_second=200_000.0)  # 1s already clips hard
    config = FlatWizardConfig(
        camera_id="cam_1", filters=[FlatWizardFilterSpec(count=10)], seed_duration=1.0,
    )
    run = FlatWizardRun(config=config, total_filters=1)
    engine = _engine(_make_app(imager))

    result = await engine._solve_filter(run, config.filters[0], 0)

    assert result.status == "solved"
    assert result.trials[0].saturated is True
    assert result.trials[-1].saturated is False


@pytest.mark.asyncio
async def test_solve_filter_fails_when_saturated_at_minimum_duration() -> None:
    imager = LinearFakeImager(gain_per_second=1e9)
    config = FlatWizardConfig(
        camera_id="cam_1", filters=[FlatWizardFilterSpec(count=10)],
        seed_duration=0.001, min_duration=0.001,
    )
    run = FlatWizardRun(config=config, total_filters=1)
    engine = _engine(_make_app(imager))

    result = await engine._solve_filter(run, config.filters[0], 0)

    assert result.status == "failed"
    assert "minimum exposure" in (result.error or "")


@pytest.mark.asyncio
async def test_solve_filter_fails_when_panel_too_dim_for_max_duration() -> None:
    """Too dim to ever reach the target even at the exposure-duration cap: the
    duration proposal keeps clamping to the same max value — must not spin
    forever on max_attempts."""
    imager = LinearFakeImager(gain_per_second=1.0)
    config = FlatWizardConfig(
        camera_id="cam_1", filters=[FlatWizardFilterSpec(count=10)],
        seed_duration=5.0, max_duration=5.0,
    )
    run = FlatWizardRun(config=config, total_filters=1)
    engine = _engine(_make_app(imager))

    result = await engine._solve_filter(run, config.filters[0], 0)

    assert result.status == "failed"
    assert len(result.trials) == 1  # stuck detected right after the first trial


# ── Filter wheel ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_solve_filter_fails_without_a_filter_wheel_when_one_is_requested() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0)
    config = FlatWizardConfig(camera_id="cam_1", filters=[FlatWizardFilterSpec(filter_name="Ha", count=10)])
    run = FlatWizardRun(config=config, total_filters=1)
    engine = _engine(_make_app(imager))

    result = await engine._solve_filter(run, config.filters[0], 0)

    assert result.status == "failed"
    assert "filter wheel" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_solve_filter_selects_the_requested_slot() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0)
    fwm = AsyncMock()
    fwm.get_status.return_value = SimpleNamespace(filter_names=["L", "Ha", "OIII"], current_slot=1)
    config = FlatWizardConfig(
        camera_id="cam_1", filter_wheel_id="fw_1",
        filters=[FlatWizardFilterSpec(filter_name="Ha", count=10)],
    )
    run = FlatWizardRun(config=config, total_filters=1)
    engine = _engine(_make_app(imager, fwm))

    result = await engine._solve_filter(run, config.filters[0], 0)

    assert result.status == "solved"
    fwm.select_filter.assert_awaited_once_with("fw_1", 2)


# ── Queueing on the sequencer ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_queues_only_solved_filters() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0)
    sequencer = AsyncMock()
    sequencer.add.return_value = SimpleNamespace(task=SimpleNamespace(id="task_123"))
    app = _make_app(imager)
    app.state.sequencer = sequencer

    config = FlatWizardConfig(
        camera_id="cam_1",
        filters=[
            FlatWizardFilterSpec(count=10),
            FlatWizardFilterSpec(filter_name="Ha", count=5),  # no wheel configured -> fails
        ],
    )
    engine = _engine(app)
    run = await engine.start(config)
    task = engine._task
    assert task is not None
    await task

    assert run.status == "completed"
    assert run.task_id == "task_123"
    assert [r.status for r in run.results] == ["solved", "failed"]

    queued_task = sequencer.add.await_args.args[0]
    assert len(queued_task.lanes) == 1
    assert len(queued_task.lanes[0].groups) == 1
    assert queued_task.lanes[0].groups[0].count == 10


@pytest.mark.asyncio
async def test_start_raises_without_a_sequencer() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0)
    engine = _engine(_make_app(imager))
    config = FlatWizardConfig(camera_id="cam_1", filters=[FlatWizardFilterSpec(count=10)])

    with pytest.raises(ValueError, match="sequencer"):
        await engine.start(config)
