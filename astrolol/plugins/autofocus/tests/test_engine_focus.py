"""AutofocusEngine.focus(): the awaitable entry point used by the sequencer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from astrolol.core.events import EventBus
from astrolol.plugins.autofocus import engine as engine_mod
from astrolol.plugins.autofocus.engine import AutofocusEngine
from astrolol.plugins.autofocus.models import AutofocusSettings
from tests.conftest import make_fake_fits

BEST = 1000


class Focuser:
    def __init__(self, position: int = 900) -> None:
        self.position = position
        self.moves: list[int] = []
        self.gate: asyncio.Event | None = None

    async def move_to(self, position: int) -> None:
        if self.gate is not None:
            await self.gate.wait()
        self.moves.append(position)
        self.position = position

    async def get_status(self) -> Any:
        return SimpleNamespace(position=self.position)


class Camera:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.n = 0

    async def expose(self, params: Any) -> Any:
        self.n += 1
        return SimpleNamespace(
            fits_path=str(make_fake_fits(self.tmp / f"af_{self.n}.fits", 16, 16))
        )


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(engine_mod.settings, "images_dir", tmp_path / "images")
    focuser = Focuser()
    camera = Camera(tmp_path)
    dm = SimpleNamespace(get_camera=lambda _id: camera, get_focuser=lambda _id: focuser)
    stars = {"on": True}

    async def fake_detect(
        fits_path: str, metric: str = "fwhm", reference_stars: list[Any] | None = None,
    ) -> tuple[float, int, list[Any]]:
        if not stars["on"]:
            return 0.0, 0, []
        fwhm = 2.0 + ((focuser.position - BEST) / 100) ** 2  # parabola around BEST
        return fwhm, 25, []

    monkeypatch.setattr(engine_mod, "detect_stars", fake_detect)
    settings = AutofocusSettings(step_size=50, num_steps=3, exposure_time=1.0)
    eng = AutofocusEngine(EventBus(), dm, settings_provider=lambda: settings)  # type: ignore[arg-type]
    return SimpleNamespace(engine=eng, focuser=focuser, camera=camera, stars=stars)


async def test_focus_uses_saved_settings_and_finds_the_minimum(rig: SimpleNamespace) -> None:
    run = await rig.engine.focus("cam", "foc")
    assert run.status == "completed"
    assert run.total_steps == 7  # num_steps=3 each side
    assert run.initial_position == 900  # where the focuser was before the run
    assert rig.focuser.moves[:7] == [750, 800, 850, 900, 950, 1000, 1050]
    assert abs(rig.focuser.position - BEST) <= 10  # moved to the fitted optimum


async def test_no_stars_is_a_sky_problem_and_focus_is_restored(rig: SimpleNamespace) -> None:
    rig.stars["on"] = False
    run = await rig.engine.focus("cam", "foc")
    assert run.status == "failed"
    assert run.sky_problem is True
    assert rig.focuser.position == 900  # back where it started


async def test_cancelling_focus_aborts_and_restores(rig: SimpleNamespace) -> None:
    rig.focuser.gate = asyncio.Event()
    task = asyncio.create_task(rig.engine.focus("cam", "foc"))
    await asyncio.sleep(0.01)
    task.cancel()
    rig.focuser.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rig.engine.current_run.status == "aborted"
    assert rig.focuser.position == 900


async def test_bad_curve_fit_fails_and_restores_focus(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flat/noisy response (no real V shape) must not be reported as success."""
    async def fake_detect_monotonic(
        fits_path: str, metric: str = "fwhm", reference_stars: list[Any] | None = None,
    ) -> tuple[float, int, list[Any]]:
        # Strictly increasing with no turning point -> never fits a valid V/U in range
        fwhm = 2.0 + (focuser.position - 750) * 0.001
        return fwhm, 25, []

    focuser = rig.focuser
    monkeypatch.setattr(engine_mod, "detect_stars", fake_detect_monotonic)

    run = await rig.engine.focus("cam", "foc")
    assert run.status == "failed"
    assert run.curve_fit is None
    assert rig.focuser.position == 900  # restored to where it started


async def test_manual_start_position_moves_there_first_and_restores_original(
    rig: SimpleNamespace,
) -> None:
    from astrolol.plugins.autofocus.models import AutofocusConfig

    config = AutofocusConfig(
        camera_id="cam", focuser_id="foc",
        step_size=50, num_steps=3, exposure_time=1.0, start_position=BEST,
    )
    run = await rig.engine.start(config)
    task = rig.engine._task
    assert task is not None
    await task

    assert run.status == "completed"
    assert run.initial_position == 900  # the original position, not the manual start
    assert rig.focuser.moves[0] == BEST  # moved to the manual start position first
    assert rig.focuser.moves[1:8] == [850, 900, 950, 1000, 1050, 1100, 1150]  # centred on BEST


async def test_lock_stars_freezes_the_reference_population_after_the_first_step(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With lock_stars on, the reference set passed to detect_stars should be None on
    step 1 (nothing to lock onto yet), then frozen to exactly step 1's detected stars
    for every later step — not re-derived from each step's own detection."""
    from astrolol.plugins.autofocus.models import AutofocusConfig

    calls: list[list[Any] | None] = []
    step1_stars = [{"x": 10.0, "y": 10.0, "fwhm": 2.5}, {"x": 50.0, "y": 50.0, "fwhm": 2.6}]

    async def fake_detect(
        fits_path: str, metric: str = "fwhm", reference_stars: list[Any] | None = None,
    ) -> tuple[float, int, list[Any]]:
        calls.append(reference_stars)
        fwhm = 2.0 + ((rig.focuser.position - BEST) / 100) ** 2
        return fwhm, len(step1_stars), step1_stars

    monkeypatch.setattr(engine_mod, "detect_stars", fake_detect)

    config = AutofocusConfig(
        camera_id="cam", focuser_id="foc",
        step_size=50, num_steps=3, exposure_time=1.0, lock_stars=True,
    )
    run = await rig.engine.start(config)
    task = rig.engine._task
    assert task is not None
    await task

    assert run.status == "completed"
    assert calls[0] is None  # nothing to lock onto for the first step
    assert all(c == step1_stars for c in calls[1:])  # frozen for every later step


async def test_focus_while_running_is_refused(rig: SimpleNamespace) -> None:
    rig.focuser.gate = asyncio.Event()
    first = asyncio.create_task(rig.engine.focus("cam", "foc"))
    await asyncio.sleep(0.01)
    with pytest.raises(ValueError):
        await rig.engine.focus("cam", "foc")
    rig.focuser.gate.set()
    await first


# ── The minimum lies beyond the swept range (after a filter change, say) ──────────────

def _focus_at(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, best: int) -> None:
    """Stars whose HFD is a V around *best* (hyperbolic: round bottom, straight arms)."""
    async def detect(
        fits_path: str, metric: str = "fwhm", reference_stars: list[Any] | None = None,
    ) -> tuple[float, int, list[Any]]:
        d = rig.focuser.position - best
        return 2.0 + 0.02 * ((d * d + 60 * 60) ** 0.5 - 60), 25, []

    monkeypatch.setattr(engine_mod, "detect_stars", detect)


@pytest.mark.parametrize("best", [1400, 500])
async def test_a_minimum_beyond_the_sweep_is_found_with_more_sweeps(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, best: int,
) -> None:
    """Start 900, sweep 750-1050: a focus at 1400 (or 500) is out of range and used to fail."""
    _focus_at(rig, monkeypatch, best)

    run = await rig.engine.focus("cam", "foc")

    assert run.status == "completed", run.error
    assert abs(run.optimal_position - best) <= 30
    assert abs(rig.focuser.position - best) <= 30
    assert run.total_steps > 7 and run.total_steps == len(run.data_points)
    positions = [dp.position for dp in run.data_points]
    assert len(positions) == len(set(positions))        # no position measured twice
    assert positions[:7] == [750, 800, 850, 900, 950, 1000, 1050]
    assert [dp.step for dp in run.data_points] == list(range(1, len(positions) + 1))


async def test_a_minimum_inside_the_sweep_needs_no_more_sweeps(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _focus_at(rig, monkeypatch, 1000)

    run = await rig.engine.focus("cam", "foc")

    assert run.status == "completed"
    assert run.total_steps == 7 and len(run.data_points) == 7


async def test_a_focus_too_far_away_fails_with_the_direction_and_restores_focus(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _focus_at(rig, monkeypatch, 6000)

    run = await rig.engine.focus("cam", "foc")

    assert run.status == "failed"
    assert "beyond the swept range" in run.error and "higher" in run.error
    assert rig.focuser.position == 900                  # back where it started
    assert run.total_steps == len(run.data_points) <= 7 + 2 * 11


def _run(points: list[tuple[int, float, int]], fit_at: float | None = None):  # noqa: ANN202
    from astrolol.plugins.autofocus.models import AutofocusConfig, AutofocusRun, CurveFit, FocusDataPoint

    run = AutofocusRun(
        config=AutofocusConfig(camera_id="c", focuser_id="f", step_size=50, num_steps=3),
        data_points=[FocusDataPoint(step=i + 1, position=p, fwhm=v, star_count=n) for i, (p, v, n) in enumerate(points)],
    )
    if fit_at is not None:
        run.curve_fit = CurveFit(a=1.0, b=0.0, c=0.0, optimal_position=fit_at)
    return run


def test_next_sweep_goes_past_the_end_where_the_curve_is_still_falling() -> None:
    from astrolol.plugins.autofocus.engine import next_sweep

    run = _run([(750, 5.0, 20), (800, 4.0, 20), (850, 3.0, 20), (900, 2.5, 20), (950, 2.2, 20), (1000, 2.1, 20), (1050, 2.0, 20)])

    assert next_sweep(run) == [1100, 1150, 1200, 1250, 1300]   # on the grid, outward from the end


def test_next_sweep_is_empty_when_the_minimum_is_bracketed_or_unclear() -> None:
    from astrolol.plugins.autofocus.engine import next_sweep

    v = [(750, 4.0, 20), (800, 3.0, 20), (850, 2.2, 20), (900, 2.0, 20), (950, 2.3, 20), (1000, 3.1, 20), (1050, 4.2, 20)]
    assert next_sweep(_run(v)) is None                                      # best sample in the middle
    assert next_sweep(_run(v, fit_at=905.0)) is None                       # valid fit inside the range
    noisy = [(750, 3.0, 20), (800, 2.6, 20), (850, 4.0, 20), (900, 2.0, 20), (950, 5.0, 20), (1000, 3.0, 20), (1050, 4.0, 20)]
    assert next_sweep(_run(noisy)) is None                                  # best in the middle, no fit: noise
    assert next_sweep(_run([(750, 2.0, 20), (800, 0.0, 0), (850, 0.0, 0)])) is None   # too few stars to steer by


def test_next_sweep_follows_an_extrapolated_fit_and_stops_at_zero() -> None:
    from astrolol.plugins.autofocus.engine import next_sweep

    v = [(750, 4.0, 20), (800, 3.0, 20), (850, 2.2, 20), (900, 2.0, 20), (950, 2.3, 20), (1000, 3.1, 20), (1050, 4.2, 20)]
    assert next_sweep(_run(v, fit_at=1120.0)) is not None                  # the fit itself points outside

    low = [(0, 2.0, 20), (50, 2.5, 20), (100, 3.0, 20), (150, 3.5, 20), (200, 4.0, 20), (250, 4.5, 20), (300, 5.0, 20)]
    assert next_sweep(_run(low)) is None                                    # cannot go below position 0


def test_next_sweep_also_extends_towards_an_end_with_no_arm_left_to_fit() -> None:
    """The best sample one step from the end: no valid fit is possible there, so the sweep
    must go on that way (the failure seen after changing filter)."""
    from astrolol.plugins.autofocus.engine import next_sweep

    near_end = [(750, 6.0, 20), (800, 5.0, 20), (850, 4.0, 20), (900, 3.2, 20), (950, 2.6, 20), (1000, 2.0, 20), (1050, 2.5, 20)]
    assert next_sweep(_run(near_end)) == [1100, 1150, 1200, 1250, 1300]
    near_start = [(750, 2.6, 20), (800, 2.0, 20), (850, 2.6, 20), (900, 3.2, 20), (950, 4.0, 20), (1000, 5.0, 20), (1050, 6.0, 20)]
    assert next_sweep(_run(near_start)) == [700, 650, 600, 550, 500]
    assert next_sweep(_run([(750, 3.0, 20), (800, 2.6, 20), (850, 2.0, 20), (900, 2.6, 20), (950, 3.0, 20), (1000, 4.0, 20), (1050, 5.0, 20)])) is None  # two samples each side


async def test_a_minimum_one_step_inside_the_end_of_a_wide_sweep_is_found(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parabola fit (the page's default) of a V-shaped curve whose centre is 100 steps from the
    end of an 11-point sweep with 100-step spacing: the fit is rejected, which ended the run."""
    from astrolol.plugins.autofocus.models import AutofocusConfig

    rig.focuser.position = 22900
    _focus_at(rig, monkeypatch, 23300)
    config = AutofocusConfig(camera_id="cam", focuser_id="foc", step_size=100, num_steps=5, exposure_time=1.0)

    run = await rig.engine.start(config)
    await rig.engine._task

    assert run.status == "completed", run.error
    assert abs(run.optimal_position - 23300) <= 40
    assert len(run.data_points) > 11


async def test_a_completed_run_says_how_far_it_can_be_trusted(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = rig.engine._bus.subscribe()
    _focus_at(rig, monkeypatch, 900)

    run = await rig.engine.focus("cam", "foc")

    assert run.quality is not None
    assert (run.quality.verdict, run.quality.causes) == ("good", [])
    assert run.curve_fit is not None and run.curve_fit.r_squared > 0.9
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    done = [e for e in events if e.type == "autofocus.completed"]
    assert len(done) == 1 and done[0].quality == "good" and done[0].causes == []


async def test_a_minimum_close_to_the_end_of_the_sweep_is_reported_as_an_edge(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sweep 750-1050 with the minimum at 1000: accepted, but only one sample lies beyond it."""
    _focus_at(rig, monkeypatch, 1000)

    run = await rig.engine.focus("cam", "foc")

    assert run.status == "completed"
    assert run.quality.verdict == "poor" and run.quality.causes == ["edge"]
