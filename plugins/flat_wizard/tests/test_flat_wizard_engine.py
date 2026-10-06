"""Tests for the flat wizard trial-and-error exposure solver."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrolol.core.events import EventBus
from astrolol.core.events.models import ImageStats
from astrolol.imaging.models import ExposureRequest
from plugins.flat_wizard.engine import FlatWizardEngine, _round_significant
from plugins.flat_wizard.models import (
    FlatWizardCameraSpec,
    FlatWizardConfig,
    FlatWizardFilterSpec,
    FlatWizardRun,
)

FULL_SCALE = 65535.0


def _stats(mean: float) -> ImageStats:
    return ImageStats(
        histogram=[], hist_min=0, hist_max=FULL_SCALE, stretch_low=0, stretch_high=0,
        mean=mean, median=mean,
    )


class LinearFakeImager:
    """A flat's mean ADU response is linear in exposure duration: mean = duration * gain,
    clipped at the sensor's full-scale ADU once the frame is actually saturated.

    Tracks the last frame per camera (like the real imager) and, with *delay*, how many
    exposures were in flight at once."""

    def __init__(self, gain_per_second: float, delay: float = 0.0) -> None:
        self.gain_per_second = gain_per_second
        self.delay = delay
        self.exposures: list[tuple[str, ExposureRequest]] = []
        self._last_mean: dict[str, float] = {}
        self.in_flight = 0
        self.max_in_flight = 0

    async def expose(self, camera_id: str, request: ExposureRequest) -> None:
        self.exposures.append((camera_id, request))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1
        self._last_mean[camera_id] = min(request.duration * self.gain_per_second, FULL_SCALE)

    def get_last_stats(self, camera_id: str) -> ImageStats:
        return _stats(self._last_mean[camera_id])


def _config(*filters: FlatWizardFilterSpec, filter_wheel_id: str | None = None, **kwargs) -> FlatWizardConfig:
    """Single-camera config (cam_1)."""
    return FlatWizardConfig(
        cameras=[FlatWizardCameraSpec(camera_id="cam_1", filter_wheel_id=filter_wheel_id, filters=list(filters))],
        **kwargs,
    )


async def _solve_first(engine: FlatWizardEngine, config: FlatWizardConfig):
    run = FlatWizardRun(config=config, total_filters=1)
    camera = config.cameras[0]
    return await engine._solve_filter(run, camera, camera.filters[0], 0)


async def _run_to_end(engine: FlatWizardEngine, config: FlatWizardConfig) -> FlatWizardRun:
    run = await engine.start(config)
    assert engine._task is not None
    await engine._task
    return run


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
    config = _config(FlatWizardFilterSpec(count=10), seed_duration=0.5)
    engine = _engine(_make_app(imager))

    result = await _solve_first(engine, config)

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
    config = _config(FlatWizardFilterSpec(count=10), seed_duration=1.0)
    engine = _engine(_make_app(imager))

    result = await _solve_first(engine, config)

    assert result.status == "solved"
    assert result.trials[0].saturated is True
    assert result.trials[-1].saturated is False


@pytest.mark.asyncio
async def test_solve_filter_fails_when_saturated_at_minimum_duration() -> None:
    imager = LinearFakeImager(gain_per_second=1e9)
    config = _config(FlatWizardFilterSpec(count=10), seed_duration=0.001, min_duration=0.001)
    engine = _engine(_make_app(imager))

    result = await _solve_first(engine, config)

    assert result.status == "failed"
    assert "minimum exposure" in (result.error or "")


@pytest.mark.asyncio
async def test_solve_filter_fails_when_panel_too_dim_for_max_duration() -> None:
    """Too dim to ever reach the target even at the exposure-duration cap: the
    duration proposal keeps clamping to the same max value — must not spin
    forever on max_attempts."""
    imager = LinearFakeImager(gain_per_second=1.0)
    config = _config(FlatWizardFilterSpec(count=10), seed_duration=5.0, max_duration=5.0)
    engine = _engine(_make_app(imager))

    result = await _solve_first(engine, config)

    assert result.status == "failed"
    assert len(result.trials) == 1  # stuck detected right after the first trial


# ── Filter wheel ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_solve_filter_fails_without_a_filter_wheel_when_one_is_requested() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0)
    config = _config(FlatWizardFilterSpec(filter_name="Ha", count=10))
    engine = _engine(_make_app(imager))

    result = await _solve_first(engine, config)

    assert result.status == "failed"
    assert "filter wheel" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_solve_filter_selects_the_requested_slot() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0)
    fwm = AsyncMock()
    fwm.get_status.return_value = SimpleNamespace(filter_names=["L", "Ha", "OIII"], current_slot=1)
    config = _config(FlatWizardFilterSpec(filter_name="Ha", count=10), filter_wheel_id="fw_1")
    engine = _engine(_make_app(imager, fwm))

    result = await _solve_first(engine, config)

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

    config = _config(
        FlatWizardFilterSpec(count=10),
        FlatWizardFilterSpec(filter_name="Ha", count=5),  # no wheel configured -> fails
    )
    engine = _engine(app)
    run = await _run_to_end(engine, config)

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
    config = _config(FlatWizardFilterSpec(count=10))

    with pytest.raises(ValueError, match="sequencer"):
        await engine.start(config)


# ── Several cameras ──────────────────────────────────────────────────────────

def _app_with_sequencer(imager: object, filter_wheel: object | None = None) -> tuple[SimpleNamespace, AsyncMock]:
    sequencer = AsyncMock()
    sequencer.add.return_value = SimpleNamespace(task=SimpleNamespace(id="task_multi"))
    app = _make_app(imager, filter_wheel)
    app.state.sequencer = sequencer
    return app, sequencer


def _wheel(names: list[str]) -> AsyncMock:
    fwm = AsyncMock()
    fwm.get_status.return_value = SimpleNamespace(filter_names=names, current_slot=1)
    return fwm


@pytest.mark.asyncio
async def test_several_cameras_queue_one_task_with_a_lane_each() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0)
    app, sequencer = _app_with_sequencer(imager, _wheel(["L", "R"]))
    config = FlatWizardConfig(cameras=[
        FlatWizardCameraSpec(
            camera_id="main", filter_wheel_id="fw_main", gain=100,
            filters=[FlatWizardFilterSpec(filter_name="L", count=20), FlatWizardFilterSpec(filter_name="R", count=10)],
        ),
        FlatWizardCameraSpec(camera_id="second", gain=0, filters=[FlatWizardFilterSpec(count=15)]),
    ])

    run = await _run_to_end(_engine(app), config)

    assert run.status == "completed"
    assert run.total_filters == 3
    assert {(r.camera_id, r.filter_name) for r in run.results} == {("main", "L"), ("main", "R"), ("second", None)}
    task = sequencer.add.await_args.args[0]
    assert [lane.camera_id for lane in task.lanes] == ["main", "second"]
    assert [(g.filter_name, g.count, g.gain) for g in task.lanes[0].groups] == [("L", 20, 100), ("R", 10, 100)]
    assert [(g.filter_name, g.count, g.gain) for g in task.lanes[1].groups] == [(None, 15, 0)]
    # Each camera's trial exposures use its own gain.
    assert {req.gain for cam, req in imager.exposures if cam == "main"} == {100}
    assert {req.gain for cam, req in imager.exposures if cam == "second"} == {0}


@pytest.mark.asyncio
async def test_cameras_are_solved_concurrently() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0, delay=0.02)
    app, _ = _app_with_sequencer(imager)
    config = FlatWizardConfig(cameras=[
        FlatWizardCameraSpec(camera_id=cam, filters=[FlatWizardFilterSpec(count=10)])
        for cam in ("a", "b", "c")
    ])

    await _run_to_end(_engine(app), config)

    assert imager.max_in_flight == 3


@pytest.mark.asyncio
async def test_cameras_sharing_a_filter_wheel_take_turns() -> None:
    """Two cameras behind one wheel must not move it under each other: one filter's
    whole solve (select + trials) happens under the wheel's lock."""
    imager = LinearFakeImager(gain_per_second=10_000.0, delay=0.02)
    app, _ = _app_with_sequencer(imager, _wheel(["L", "R"]))
    config = FlatWizardConfig(cameras=[
        FlatWizardCameraSpec(camera_id=cam, filter_wheel_id="shared", filters=[
            FlatWizardFilterSpec(filter_name="L", count=10), FlatWizardFilterSpec(filter_name="R", count=10),
        ])
        for cam in ("a", "b")
    ])

    run = await _run_to_end(_engine(app), config)

    assert run.status == "completed"
    assert imager.max_in_flight == 1


@pytest.mark.asyncio
async def test_a_camera_with_nothing_solved_gets_no_lane() -> None:
    imager = LinearFakeImager(gain_per_second=10_000.0)
    app, sequencer = _app_with_sequencer(imager)
    config = FlatWizardConfig(cameras=[
        FlatWizardCameraSpec(camera_id="ok", filters=[FlatWizardFilterSpec(count=10)]),
        # Filter requested without a wheel -> fails -> no lane.
        FlatWizardCameraSpec(camera_id="broken", filters=[FlatWizardFilterSpec(filter_name="Ha", count=10)]),
    ])

    run = await _run_to_end(_engine(app), config)

    assert run.status == "completed"
    assert [lane.camera_id for lane in sequencer.add.await_args.args[0].lanes] == ["ok"]


def test_a_camera_may_appear_only_once() -> None:
    spec = FlatWizardCameraSpec(camera_id="cam_1", filters=[FlatWizardFilterSpec(count=1)])
    with pytest.raises(ValueError, match="only once"):
        FlatWizardConfig(cameras=[spec, spec])
