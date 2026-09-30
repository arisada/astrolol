"""Guiding supervision, stalls and centering retries (phase 2)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from astropy.io import fits

from astrolol.core.sequencer import ExposureGroup, RunOutcome, RunState, TaskStatus
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.tests.fakes import Rig, make_task, wait_until

FAST = dict(guide_retry_interval_s=0.05, center_retry_interval_s=0.05, guide_healthy_after_s=0.0)


def _rig(tmp_path: Path, **overrides: object) -> Rig:
    return Rig(tmp_path, SequencerSettings(**{**FAST, **overrides}))  # type: ignore[arg-type]


def _no_solution() -> SimpleNamespace:
    return SimpleNamespace(
        success=False,
        failure="no_solution",
        attempts=[1],
        final_error_arcsec=None,
        message="no stars",
    )


async def test_guider_not_connected_waits_until_it_is(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.guider.connected = False
    entry = await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    await rig.svc.start()
    await wait_until(lambda: rig.svc.status().stall is not None)
    status = rig.svc.status()
    assert status.run_state == RunState.RUNNING
    assert status.activity == "waiting_for_guiding"
    assert "not connected" in (status.message or "")
    assert rig.imager.requests == []  # no frame while waiting
    await wait_until(lambda: len(rig.of("sequencer.stall_attempt")) >= 2)  # retried
    rig.guider.connected = True
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert (await rig.svc.get(entry.task.id)).runtime.stall is None
    stalled = rig.of("sequencer.task_stalled")
    unstalled = rig.of("sequencer.task_unstalled")
    assert [e.kind for e in stalled] == ["guiding"] and len(unstalled) == 1
    assert unstalled[0].attempts >= 2
    assert stalled[0].notify == "warning"
    assert unstalled[0].notify == "info"
    assert rig.of("sequencer.stall_attempt")[0].notify is None  # retries don't spam


async def test_star_lost_holds_frames_and_recovers_without_a_restart(tmp_path: Path) -> None:
    rig = _rig(tmp_path, guide_retry_interval_s=60.0)
    rig.imager.gate = asyncio.Event()
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=2)], dither_every=None))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    rig.guider.star_lost = True  # clouds during the first frame
    rig.guider.unguided_for_s = 5.0
    rig.imager.gate.set()  # the frame in progress completes
    await wait_until(lambda: rig.svc.status().activity == "waiting_for_guiding")
    assert rig.imager.saved == 1
    assert rig.svc.status().stall is None  # a short loss is not a stall
    guides = rig.guider.guides
    rig.guider.star_lost = False  # the guider found the star again by itself
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert rig.guider.guides == guides  # no restart was needed
    assert rig.imager.saved == 2


async def test_long_star_loss_is_a_stall_and_recenters_once(tmp_path: Path) -> None:
    rig = _rig(tmp_path, recenter_after_guide_loss_min=0.0)
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    rig.guider.guiding = True
    rig.guider.star_lost = True
    rig.guider.unguided_for_s = 600.0
    centers_before = len(rig.solver.calls)

    async def recover_later() -> None:
        await wait_until(lambda: len(rig.solver.calls) >= centers_before + 2)
        rig.guider.star_lost = False

    helper = asyncio.create_task(recover_later())
    assert await _run(rig) == RunOutcome.COMPLETED
    await helper
    # one centering in the setup, one re-centre during the outage — not one per retry
    assert len(rig.solver.calls) == centers_before + 2
    assert [e.kind for e in rig.of("sequencer.task_stalled")] == ["guiding"]


async def test_stall_timeout_applies_the_error_policy(tmp_path: Path) -> None:
    rig = _rig(tmp_path, stall_timeout_min=0.002)  # ~0.1 s
    rig.guider.connected = False
    a = await rig.svc.add(make_task("A", on_error="defer"))
    rig2_task = await rig.svc.add(make_task("B", start_guiding=False))
    assert await _run(rig) == RunOutcome.COMPLETED
    rt_a = (await rig.svc.get(a.task.id)).runtime
    assert rt_a.status == TaskStatus.INTERRUPTED
    assert rt_a.interruptions[-1].kind == "defer"
    assert rt_a.interruptions[-1].stall_kind == "guiding"
    assert (await rig.svc.get(rig2_task.task.id)).runtime.status == TaskStatus.COMPLETED


async def test_switch_away_during_a_stall(tmp_path: Path) -> None:
    rig = _rig(tmp_path, guide_retry_interval_s=60.0)
    rig.guider.connected = False
    a = await rig.svc.add(make_task("A"))
    b = await rig.svc.add(make_task("B", start_guiding=False))
    await rig.svc.start()
    await wait_until(lambda: rig.svc.status().stall is not None)
    await rig.svc.switch_to(b.task.id, "frame", actor="scheduler:test", reason="guiding stalled")
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    rt_a = (await rig.svc.get(a.task.id)).runtime
    assert rt_a.status == TaskStatus.INTERRUPTED
    assert rt_a.stall is None
    assert rt_a.interruptions[-1].actor == "scheduler:test"
    assert (await rig.svc.get(b.task.id)).runtime.status == TaskStatus.COMPLETED


async def test_centering_without_stars_is_retried(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.solver.results = [_no_solution(), _no_solution()]
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    assert await _run(rig) == RunOutcome.COMPLETED
    assert len(rig.solver.calls) == 3
    stalls = rig.of("sequencer.task_stalled")
    assert [e.kind for e in stalls] == ["centering"]
    assert rig.of("sequencer.task_unstalled")[0].attempts == 2


async def test_centering_that_does_not_converge_is_an_error(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.solver.results = [
        SimpleNamespace(
            success=False,
            failure="not_converged",
            attempts=[1, 2],
            final_error_arcsec=300.0,
            message="off",
        )
    ]
    entry = await rig.svc.add(make_task(on_error="skip"))
    await _run(rig)
    assert (await rig.svc.get(entry.task.id)).runtime.status == TaskStatus.FAILED
    assert rig.of("sequencer.task_stalled") == []


async def test_badly_unguided_frames_are_retaken_but_kept(tmp_path: Path) -> None:
    rig = _rig(tmp_path, uncount_if_unguided_s=10.0)
    rig.guider.unguided_s = 30.0  # every frame reports 30 s unguided
    entry = await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.saved >= 2)
    rig.guider.unguided_s = 0.0
    await rig.svc.wait_idle()
    frames = rig.of("sequencer.frame_saved")
    assert [f.counted for f in frames][:2] == [False, False] or frames[0].counted is False
    assert frames[-1].counted is True
    assert (await rig.svc.get(entry.task.id)).runtime.frames_done() == 1
    assert all(Path(f.fits_path).exists() for f in frames)


async def test_guiding_figures_are_written_to_fits(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.guider.unguided_s = 4.5
    rig.guider.losses = 1
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    await _run(rig)
    frame = rig.of("sequencer.frame_saved")[0]
    header = fits.getheader(frame.fits_path)
    assert (header["GUIDLOST"], header["GUIDLOSN"], header["GUIDRMS"]) == (4.5, 1, 0.8)


async def test_no_guider_plugin_is_not_a_stall(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.app.state.guider = None
    await rig.svc.add(make_task())
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.of("sequencer.task_stalled") == []


async def _run(rig: Rig) -> RunOutcome | None:
    await rig.svc.start()
    return await rig.svc.wait_idle()


@pytest.fixture(autouse=True)
def _quiet() -> None:
    pass


async def test_reconnected_guider_is_used_immediately(tmp_path: Path) -> None:
    rig = _rig(tmp_path, guide_retry_interval_s=60.0)
    rig.guider.connected = False
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    await rig.svc.start()
    await wait_until(lambda: rig.svc.status().stall is not None)
    rig.guider.connected = True
    # without the reconnection shortcut this would wait for the 60 s retry
    assert await asyncio.wait_for(rig.svc.wait_idle(), 2) == RunOutcome.COMPLETED


async def test_guiding_stopped_between_frames_is_restarted_and_dither_skipped(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path)
    rig.imager.gate = asyncio.Event()
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=2)], dither_every=1))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    guides = rig.guider.guides
    rig.guider.guiding = False  # guiding gave up during the first frame
    rig.imager.gate.set()
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert rig.guider.guides == guides + 1  # restarted before the second frame
    assert rig.guider.dithers == 0  # the dither due after frame 1 was skipped
    assert any(e.step == "dither" for e in rig.of("sequencer.step_skipped"))
    assert rig.of("sequencer.task_stalled") == []  # restarted at once: not a stall
