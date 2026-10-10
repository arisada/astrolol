"""Camera cooling: per-task set point, waiting for it, and warming up at the end."""

from __future__ import annotations

from pathlib import Path

import pytest

from astrolol.core.sequencer import ExposureGroup, Lane, RunOutcome
from astrolol.plugins.sequencer import steps as steps_mod
from astrolol.plugins.sequencer.settings import SequencerSettings
from astrolol.plugins.sequencer.tests.fakes import Rig, make_task


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(steps_mod, "COOLING_POLL_S", 0.01)


def _task(temp: float = -10.0, **kwargs: object):  # noqa: ANN202
    task = make_task(
        groups=[ExposureGroup(duration=1, count=1)], kind="current", ra=None, dec=None, **kwargs
    )
    task.lanes[0] = Lane(
        groups=task.lanes[0].groups, target_temperature=temp
    )
    return task


async def _run(rig: Rig) -> RunOutcome | None:
    await rig.svc.start()
    return await rig.svc.wait_idle()


async def test_task_sets_camera_temperature(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.svc.add(_task())
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.dm.camera.cooler_calls == [(True, -10.0)]


async def test_no_set_point_leaves_cooler_alone(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.svc.add(make_task(kind="current", ra=None, dec=None))
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.dm.camera.cooler_calls == []


async def test_uncooled_camera_is_skipped(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.dm.camera.temperature = None
    await rig.svc.add(_task(wait_for_temperature=True))
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.dm.camera.cooler_calls == []
    assert "cooling" in [e.step for e in rig.of("sequencer.step_skipped")]


async def test_waits_until_temperature_reached(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.dm.camera.settle_polls = 4
    await rig.svc.add(_task(wait_for_temperature=True))
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.dm.camera._reads > 4
    assert rig.imager.saved == 1


async def test_wait_times_out(tmp_path: Path) -> None:
    rig = Rig(tmp_path, SequencerSettings(cooling_timeout_min=0.0005))
    rig.dm.camera.settle_polls = 10**9
    await rig.svc.add(_task(wait_for_temperature=True, on_error="abort"))
    assert await _run(rig) == RunOutcome.FAILED
    assert rig.imager.saved == 0


async def test_warm_on_complete(tmp_path: Path) -> None:
    rig = Rig(tmp_path, SequencerSettings(warm_on_complete=True, warm_temperature_c=15.0))
    await rig.svc.add(_task())
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.dm.camera.cooler_calls == [(True, -10.0), (True, 15.0)]


async def test_no_warming_by_default(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.svc.add(_task())
    await _run(rig)
    assert rig.dm.camera.cooler_calls == [(True, -10.0)]
