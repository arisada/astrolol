"""Autofocus triggers, runs and autofocus stalls in the sequencer."""

from __future__ import annotations

import time
from pathlib import Path

from astrolol.core.sequencer import ExposureGroup, Lane, RunOutcome, TaskStatus
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.tests.fakes import Rig, af_no_stars, make_task


def _rig(tmp_path: Path, **settings: object) -> Rig:
    return Rig(tmp_path, SequencerSettings(**settings))  # type: ignore[arg-type]


async def _run(rig: Rig) -> RunOutcome | None:
    await rig.svc.start()
    return await rig.svc.wait_idle()


async def test_autofocus_at_start(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    await rig.svc.add(
        make_task(groups=[ExposureGroup(duration=1, count=2)], autofocus_at_start=True)
    )
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.autofocus.calls == [("cam1", "foc1")]
    done = [e for e in rig.of("sequencer.step_finished") if e.step == "autofocus"]
    assert done[0].details["reason"] == "task start" and done[0].details["position"] == 1000


async def test_autofocus_on_each_filter_change(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.fwm.slot = None
    task = make_task(dither_every=None)
    groups = [
        ExposureGroup(filter_name="R", duration=1, count=2),
        ExposureGroup(filter_name="G", duration=1, count=1),
    ]
    task.lanes = [Lane(groups=groups, autofocus_on_filter_change=True)]
    await rig.svc.add(task)
    await _run(rig)
    reasons = [
        e.details["reason"] for e in rig.of("sequencer.step_finished") if e.step == "autofocus"
    ]
    assert reasons == ["filter R", "filter G"]


async def test_no_autofocus_without_triggers(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    await rig.svc.add(make_task())
    await _run(rig)
    assert rig.autofocus.calls == []


async def test_temperature_trigger(tmp_path: Path) -> None:
    rig = _rig(tmp_path, autofocus_on_temp_delta=1.0)
    rig.imager.gate = None
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=3)], dither_every=None))
    original = rig.imager.expose

    async def cooling(camera_id: str, req: object) -> object:
        rig.dm.focuser.temperature = (rig.dm.focuser.temperature or 0) - 0.6  # 0.6 °C per frame
        return await original(camera_id, req)

    rig.imager.expose = cooling  # type: ignore[method-assign]
    await _run(rig)
    reasons = [
        e.details["reason"] for e in rig.of("sequencer.step_finished") if e.step == "autofocus"
    ]
    assert len(reasons) == 1 and "temperature" in reasons[0]


async def test_time_trigger(tmp_path: Path) -> None:
    rig = _rig(tmp_path, autofocus_every_min=0.0005)  # 30 ms
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=3)], dither_every=None))
    original = rig.imager.expose

    async def slow(camera_id: str, req: object) -> object:
        time.sleep(0.04)
        return await original(camera_id, req)

    rig.imager.expose = slow  # type: ignore[method-assign]
    await _run(rig)
    assert len(rig.autofocus.calls) == 2  # before frames 2 and 3


async def test_refocus_after_flip(tmp_path: Path) -> None:
    rig = _rig(tmp_path, refocus_after_flip=True)
    rig.mount.set_ha(0.3)
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    await _run(rig)
    assert rig.mount.flips == 1
    reasons = [
        e.details["reason"] for e in rig.of("sequencer.step_finished") if e.step == "autofocus"
    ]
    assert reasons == ["after the meridian flip"]


async def test_no_stars_is_a_stall_and_imaging_continues(tmp_path: Path) -> None:
    rig = _rig(tmp_path, autofocus_retry_interval_s=0.001)
    rig.autofocus.results = [af_no_stars()]
    entry = await rig.svc.add(
        make_task(
            groups=[ExposureGroup(duration=1, count=2)], autofocus_at_start=True, dither_every=None
        )
    )
    assert await _run(rig) == RunOutcome.COMPLETED
    assert (await rig.svc.get(entry.task.id)).runtime.frames_done() == 2
    assert [e.kind for e in rig.of("sequencer.task_stalled")] == ["autofocus"]
    assert len(rig.of("sequencer.task_unstalled")) == 1  # the retry before frame 1 worked
    assert len(rig.autofocus.calls) == 2


async def test_autofocus_device_failure_uses_the_error_policy(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.autofocus.results = [
        type(af_no_stars())(
            status="failed",
            error="focuser timeout",
            sky_problem=False,
            optimal_position=None,
            data_points=[],
        )
    ]
    entry = await rig.svc.add(make_task(autofocus_at_start=True, on_error="skip"))
    await _run(rig)
    rt = (await rig.svc.get(entry.task.id)).runtime
    assert rt.status == TaskStatus.FAILED and "focuser timeout" in (rt.last_error or "")


async def test_autofocus_without_plugin_or_focuser_is_skipped(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.app.state.autofocus_engine = None
    await rig.svc.add(make_task(autofocus_at_start=True))
    report = await rig.svc.preflight()
    assert any(i.code == "no_autofocus" for i in report.issues)
    assert await _run(rig) == RunOutcome.COMPLETED
    assert any(e.step == "autofocus" for e in rig.of("sequencer.step_skipped"))
