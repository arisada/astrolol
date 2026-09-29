"""AutofocusEngine.focus(): the awaitable entry point used by the sequencer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from astrolol.core.events import EventBus
from plugins.autofocus import engine as engine_mod
from plugins.autofocus.engine import AutofocusEngine
from plugins.autofocus.models import AutofocusSettings
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
    from plugins.autofocus.models import AutofocusConfig

    config = AutofocusConfig(
        camera_id="cam", focuser_id="foc",
        step_size=50, num_steps=3, exposure_time=1.0, start_position=BEST,
    )
    run = await rig.engine.start(config)
    task = rig.engine._task
    assert task is not None
    await task

    assert run.status == "completed"
    assert rig.focuser.moves[0] == BEST  # moved to the manual start position first
    assert rig.focuser.moves[1:8] == [850, 900, 950, 1000, 1050, 1100, 1150]  # centred on BEST


async def test_lock_stars_freezes_the_reference_population_after_the_first_step(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With lock_stars on, the reference set passed to detect_stars should be None on
    step 1 (nothing to lock onto yet), then frozen to exactly step 1's detected stars
    for every later step — not re-derived from each step's own detection."""
    from plugins.autofocus.models import AutofocusConfig

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
