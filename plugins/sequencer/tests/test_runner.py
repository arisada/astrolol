"""Runner behaviour: lifecycle, boundaries, error policies, switching, flips."""

from __future__ import annotations

from pathlib import Path

import pytest

from astrolol.core.sequencer import (
    ExposureGroup,
    Lane,
    PreflightFailed,
    RunOutcome,
    RunState,
    SequencerBusy,
    TaskStatus,
)
from plugins.sequencer import runner as runner_mod
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.tests.fakes import Rig, make_task, wait_until


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


async def _run_to_end(rig: Rig, **start: object) -> RunOutcome | None:
    await rig.svc.start(**start)  # type: ignore[arg-type]
    return await rig.svc.wait_idle()


# ── Happy path ────────────────────────────────────────────────────────────────


async def test_run_completes_and_records_progress(rig: Rig) -> None:
    entry = await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=3)]))
    assert await _run_to_end(rig) == RunOutcome.COMPLETED

    got = await rig.svc.get(entry.task.id)
    assert got.runtime.status == TaskStatus.COMPLETED
    assert got.runtime.frames_done() == 3
    assert rig.imager.saved == 3
    assert len(rig.mount.slews) == 1
    assert len(rig.solver.calls) == 1
    assert rig.guider.guides == 1
    # dither_every=1: between frames, not after the last one
    assert rig.guider.dithers == 2
    assert [e.frame_idx for e in rig.of("sequencer.frame_saved")] == [0, 1, 2]
    assert rig.svc.status().run_state == RunState.IDLE


async def test_completed_run_notifies_info(rig: Rig) -> None:
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    assert await _run_to_end(rig) == RunOutcome.COMPLETED
    finished = rig.of("sequencer.session_finished")
    assert finished[-1].notify == "info"


async def test_stopped_run_does_not_notify(rig: Rig) -> None:
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=2)]))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.stop("frame")
    assert await rig.svc.wait_idle() == RunOutcome.STOPPED
    finished = rig.of("sequencer.session_finished")
    assert finished[-1].notify is None


async def test_frames_are_named_after_the_target(rig: Rig) -> None:
    await rig.svc.add(make_task(name="Orion Nebula", groups=[ExposureGroup(duration=1, count=1)]))
    await _run_to_end(rig)
    _, req = rig.imager.requests[0]
    assert req.object_name == "Orion Nebula"
    assert req.save is True


async def test_filter_changes_once_per_group(rig: Rig) -> None:
    rig.fwm.slot = 5  # Ha
    groups = [
        ExposureGroup(filter_name="R", duration=1, count=3),
        ExposureGroup(filter_name="G", duration=1, count=2),
    ]
    await rig.svc.add(make_task(groups=groups, dither_every=None))
    await _run_to_end(rig)
    assert rig.fwm.selected == [2, 3]
    assert rig.imager.saved == 5


async def test_round_robin_order(rig: Rig) -> None:
    rig.fwm.slot = None
    groups = [
        ExposureGroup(filter_name="R", duration=1, count=2),
        ExposureGroup(filter_name="G", duration=1, count=3),
    ]
    task = make_task(dither_every=None)
    task.lanes = [Lane(groups=groups, order="round_robin", round_robin_batch=1)]
    await rig.svc.add(task)
    await _run_to_end(rig)
    # R G R G G, one filter change per visit
    assert rig.fwm.selected == [2, 3, 2, 3]
    assert rig.imager.saved == 5


async def test_dither_cadence(rig: Rig) -> None:
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=7)], dither_every=3))
    await _run_to_end(rig)
    assert rig.guider.dithers == 2  # after frames 3 and 6


async def test_current_target_does_not_slew_or_center(rig: Rig) -> None:
    await rig.svc.add(make_task(kind="current", ra=None, dec=None))
    await _run_to_end(rig)
    assert rig.mount.slews == []
    assert rig.solver.calls == []
    assert any(e.step == "center" for e in rig.of("sequencer.step_skipped"))


async def test_missing_plugins_are_reported_not_fatal(rig: Rig) -> None:
    rig.app.state.guider = None
    rig.app.state.solve_manager = None
    await rig.svc.add(make_task())
    assert await _run_to_end(rig) == RunOutcome.COMPLETED
    skipped = {e.step for e in rig.of("sequencer.step_skipped")}
    assert {"center", "start_guiding", "dither"} <= skipped


async def test_auto_flip_suspended_during_run(rig: Rig) -> None:
    rig.imager.gate = __import__("asyncio").Event()
    await rig.svc.add(make_task())
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    assert rig.mount.suspended == 1
    rig.imager.gate.set()
    await rig.svc.wait_idle()
    assert rig.mount.suspended == 0


async def test_second_start_is_rejected(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    await rig.svc.add(make_task())
    await rig.svc.start()
    with pytest.raises(SequencerBusy):
        await rig.svc.start()
    rig.imager.gate.set()
    await rig.svc.wait_idle()


async def test_park_on_complete(tmp_path: Path) -> None:
    rig = Rig(tmp_path, SequencerSettings(park_on_complete=True))
    await rig.svc.add(make_task())
    await _run_to_end(rig)
    assert rig.mount.events[-1] == "park"


async def test_unpark_on_start(rig: Rig) -> None:
    rig.mount.parked = True
    await rig.svc.add(make_task())
    await _run_to_end(rig)
    assert rig.mount.events[0] == "unpark"


# ── Pre-flight ────────────────────────────────────────────────────────────────


async def test_preflight_unknown_filter_blocks_start(rig: Rig) -> None:
    await rig.svc.add(make_task(groups=[ExposureGroup(filter_name="OIII", duration=1, count=1)]))
    with pytest.raises(PreflightFailed) as exc:
        await rig.svc.start()
    assert [i.code for i in exc.value.report.issues if i.severity == "error"] == [
        "filter_not_in_wheel"
    ]
    assert rig.svc.status().run_state == RunState.IDLE


async def test_preflight_nothing_to_run(rig: Rig) -> None:
    report = await rig.svc.preflight()
    assert not report.ok
    assert report.issues[0].code == "nothing_to_run"


async def test_preflight_camera_and_lanes(rig: Rig) -> None:
    task = make_task()
    task.lanes = [
        Lane(camera_id="nope", groups=[ExposureGroup(duration=1, count=1)]),
        Lane(groups=[ExposureGroup(duration=1, count=1)]),
    ]
    await rig.svc.add(task)
    codes = {i.code for i in (await rig.svc.preflight()).issues}
    assert "camera_not_connected" in codes


async def test_preflight_warns_when_guider_disconnected(rig: Rig) -> None:
    rig.guider.connected = False
    await rig.svc.add(make_task())
    report = await rig.svc.preflight()
    assert report.ok
    assert any(i.code == "guider_disconnected" and i.severity == "warning" for i in report.issues)


# ── Pause / resume / stop / skip ──────────────────────────────────────────────


async def test_pause_at_frame_then_resume(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    entry = await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=3)]))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.pause("frame", actor="user")
    assert rig.svc.status().run_state == RunState.PAUSING
    rig.imager.gate.set()
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    assert rig.imager.saved == 1  # the in-flight frame finished
    assert (await rig.svc.get(entry.task.id)).runtime.status == TaskStatus.RUNNING

    await rig.svc.resume(actor="user")
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert rig.imager.saved == 3
    assert len(rig.mount.slews) == 1  # short pause: no setup re-run
    resumed = rig.of("sequencer.resumed")
    assert resumed and resumed[0].setup_rerun is False
    kinds = [i.kind for i in (await rig.svc.get(entry.task.id)).runtime.interruptions]
    assert kinds == ["pause"]


async def test_pause_now_discards_the_frame(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    entry = await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=2)]))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.pause("now")
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    assert rig.imager.cancelled == 1
    assert (await rig.svc.get(entry.task.id)).runtime.frames_done() == 0
    assert len(rig.of("sequencer.frame_discarded")) == 1

    rig.imager.gate.set()
    await rig.svc.resume()
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert (await rig.svc.get(entry.task.id)).runtime.frames_done() == 2


async def test_resume_reselects_filter_moved_during_pause(rig: Rig) -> None:
    """A pause can let something else (e.g. a manual autofocus run) move the filter
    wheel. On resume the sequencer must not trust its cached "last filter we set" and
    skip re-selecting — it has to re-assert the task's filter before the next frame."""
    import asyncio

    rig.imager.gate = asyncio.Event()
    rig.fwm.slot = 5  # Ha
    groups = [ExposureGroup(filter_name="R", duration=1, count=2)]
    await rig.svc.add(make_task(groups=groups, dither_every=None))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.pause("frame", actor="user")
    rig.imager.gate.set()
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    assert rig.fwm.selected == [2]  # R selected before the first frame

    # Something external (manual autofocus, INDI panel, ...) moves the wheel away.
    rig.fwm.slot = 1

    await rig.svc.resume(actor="user")
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    # The second frame must re-select R rather than trusting the stale cache.
    assert rig.fwm.selected == [2, 2]


async def test_resume_does_not_autofocus_when_the_filter_never_moved(rig: Rig) -> None:
    """Invalidating the cached filter on resume (above) must not also fire an unwanted
    autofocus: _prepare_frame's change_filter call is now a no-op (the wheel was already
    on the right slot — nothing disturbed it during the pause), and only an actual move
    should arm autofocus_on_filter_change."""
    import asyncio

    rig.imager.gate = asyncio.Event()
    rig.fwm.slot = 1  # not yet on R (slot 2) -- the first frame's change triggers autofocus
    groups = [ExposureGroup(filter_name="R", duration=1, count=2)]
    task = make_task(groups=groups, dither_every=None)
    task.lanes = [Lane(groups=groups, autofocus_on_filter_change=True)]
    await rig.svc.add(task)
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.pause("frame", actor="user")
    rig.imager.gate.set()
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    assert rig.autofocus.calls == [("cam1", "foc1")]  # only the first frame's filter change

    # Nothing touched the wheel during the pause.
    await rig.svc.resume(actor="user")
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    # No second autofocus run from the cache invalidation alone.
    assert rig.autofocus.calls == [("cam1", "foc1")]


async def test_resume_before_pause_takes_effect_cancels_it(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    await rig.svc.add(make_task())
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.pause("frame")
    await rig.svc.resume()
    assert rig.svc.status().run_state == RunState.RUNNING
    rig.imager.gate.set()
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert rig.of("sequencer.interruption") == []


async def test_long_pause_reruns_setup(tmp_path: Path) -> None:
    import asyncio

    rig = Rig(tmp_path, SequencerSettings(recenter_after_pause_min=0.0))
    rig.imager.gate = asyncio.Event()
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=2)]))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.pause("frame")
    rig.imager.gate.set()
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    await asyncio.sleep(0.01)
    await rig.svc.resume()
    await rig.svc.wait_idle()
    assert len(rig.mount.slews) == 2
    assert rig.of("sequencer.resumed")[0].setup_rerun is True


async def test_stop_at_frame_keeps_progress(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    entry = await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=5)]))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.stop("frame", actor="user", reason="clouds")
    assert rig.svc.status().run_state == RunState.STOPPING
    rig.imager.gate.set()
    assert await rig.svc.wait_idle() == RunOutcome.STOPPED
    rt = (await rig.svc.get(entry.task.id)).runtime
    assert rt.status == TaskStatus.INTERRUPTED
    assert rt.frames_done() == 1
    assert rt.interruptions[-1].kind == "stop"
    assert rt.interruptions[-1].reason == "clouds"

    # A new run resumes it: setup re-run, remaining frames only
    rig.imager.gate = None
    assert await _run_to_end(rig) == RunOutcome.COMPLETED
    rt = (await rig.svc.get(entry.task.id)).runtime
    assert rt.status == TaskStatus.COMPLETED
    assert rig.imager.saved == 5
    assert len(rig.mount.slews) == 2


async def test_cancel_aborts_exposure(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    entry = await rig.svc.add(make_task())
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.cancel(actor="user")
    assert await rig.svc.wait_idle() == RunOutcome.CANCELLED
    assert rig.imager.cancelled == 1
    rt = (await rig.svc.get(entry.task.id)).runtime
    assert rt.status == TaskStatus.INTERRUPTED
    assert rt.frames_done() == 0


async def test_stop_after_task(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    a = await rig.svc.add(make_task("A", groups=[ExposureGroup(duration=1, count=2)]))
    b = await rig.svc.add(make_task("B"))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.stop("task")
    rig.imager.gate.set()
    assert await rig.svc.wait_idle() == RunOutcome.STOPPED
    assert (await rig.svc.get(a.task.id)).runtime.status == TaskStatus.COMPLETED
    assert (await rig.svc.get(b.task.id)).runtime.status == TaskStatus.PENDING


async def test_skip_current(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    a = await rig.svc.add(make_task("A", groups=[ExposureGroup(duration=1, count=3)]))
    b = await rig.svc.add(make_task("B", groups=[ExposureGroup(duration=1, count=1)]))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.skip_current("now")
    await wait_until(lambda: rig.svc.status().current_task_id == b.task.id)
    rig.imager.gate.set()
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert (await rig.svc.get(a.task.id)).runtime.status == TaskStatus.SKIPPED
    assert (await rig.svc.get(b.task.id)).runtime.status == TaskStatus.COMPLETED


# ── Error policies ────────────────────────────────────────────────────────────


async def test_on_error_pause_then_resume_retries(rig: Rig) -> None:
    entry = await rig.svc.add(
        make_task(groups=[ExposureGroup(duration=1, count=2)], on_error="pause")
    )
    rig.imager.fail_next = [RuntimeError("camera hiccup")]
    await rig.svc.start()
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    status = rig.svc.status()
    assert "camera hiccup" in (status.pause_reason or "")
    assert (await rig.svc.get(entry.task.id)).runtime.status == TaskStatus.RUNNING

    await rig.svc.resume()
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert (await rig.svc.get(entry.task.id)).runtime.frames_done() == 2
    assert len(rig.mount.slews) == 1  # an exposure failure doesn't re-run setup


async def test_on_error_pause_setup_failure_reruns_setup(rig: Rig) -> None:
    await rig.svc.add(make_task(on_error="pause"))
    rig.mount.fail_slew = ["below horizon"]
    await rig.svc.start()
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    await rig.svc.resume()
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED
    assert len(rig.mount.slews) == 1  # the retry slewed successfully


async def test_on_error_pause_notifies(rig: Rig) -> None:
    await rig.svc.add(make_task(on_error="pause"))
    rig.mount.fail_slew = ["below horizon"]
    await rig.svc.start()
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    failed = rig.of("sequencer.step_failed")
    assert failed and failed[0].notify == "warning"
    await rig.svc.resume()
    await rig.svc.wait_idle()


async def test_on_error_skip_does_not_notify(rig: Rig) -> None:
    await rig.svc.add(make_task("A", on_error="skip"))
    await rig.svc.add(make_task("B"))
    rig.imager.fail_next = [RuntimeError("boom")]
    assert await _run_to_end(rig) == RunOutcome.COMPLETED
    failed = rig.of("sequencer.step_failed")
    assert failed and failed[0].notify is None


async def test_paused_on_error_then_stop(rig: Rig) -> None:
    entry = await rig.svc.add(make_task(on_error="pause"))
    rig.imager.fail_next = [RuntimeError("boom")]
    await rig.svc.start()
    await wait_until(lambda: rig.svc.status().run_state == RunState.PAUSED)
    await rig.svc.stop("frame")
    assert await rig.svc.wait_idle() == RunOutcome.STOPPED
    assert (await rig.svc.get(entry.task.id)).runtime.status == TaskStatus.INTERRUPTED


async def test_on_error_skip(rig: Rig) -> None:
    a = await rig.svc.add(make_task("A", on_error="skip"))
    b = await rig.svc.add(make_task("B"))
    rig.imager.fail_next = [RuntimeError("boom")]
    assert await _run_to_end(rig) == RunOutcome.COMPLETED
    rt_a = (await rig.svc.get(a.task.id)).runtime
    assert rt_a.status == TaskStatus.FAILED
    assert "boom" in (rt_a.last_error or "")
    assert (await rig.svc.get(b.task.id)).runtime.status == TaskStatus.COMPLETED


async def test_on_error_defer(tmp_path: Path) -> None:
    # Centering keeps finding no stars; after the stall timeout the task is set aside.
    rig = Rig(tmp_path, SequencerSettings(center_retry_interval_s=0.02, stall_timeout_min=0.002))
    a = await rig.svc.add(
        make_task("A", on_error="defer", groups=[ExposureGroup(duration=1, count=3)])
    )
    b = await rig.svc.add(make_task("B", center=False))
    no_stars = __import__("types").SimpleNamespace(
        success=False,
        failure="no_solution",
        attempts=[1],
        final_error_arcsec=None,
        message="no stars",
    )
    rig.solver.results = [no_stars] * 1000
    assert await _run_to_end(rig) == RunOutcome.COMPLETED
    rt_a = (await rig.svc.get(a.task.id)).runtime
    assert rt_a.status == TaskStatus.INTERRUPTED
    assert rt_a.interruptions[-1].kind == "defer"
    assert rt_a.interruptions[-1].stall_kind == "centering"
    assert rt_a.stall is None
    assert (await rig.svc.get(b.task.id)).runtime.status == TaskStatus.COMPLETED
    interruption = rig.of("sequencer.interruption")
    assert interruption[-1].notify == "warning"


async def test_on_error_abort(rig: Rig) -> None:
    a = await rig.svc.add(make_task("A", on_error="abort"))
    b = await rig.svc.add(make_task("B"))
    rig.imager.fail_next = [RuntimeError("boom")]
    assert await _run_to_end(rig) == RunOutcome.FAILED
    assert (await rig.svc.get(a.task.id)).runtime.status == TaskStatus.FAILED
    finished = rig.of("sequencer.session_finished")
    assert finished[-1].notify == "warning"
    assert (await rig.svc.get(b.task.id)).runtime.status == TaskStatus.PENDING
    assert "boom" in (rig.svc.status().last_error or "")


# ── Switching and waiting (scheduler API) ─────────────────────────────────────


async def test_switch_to_mid_run(rig: Rig) -> None:
    import asyncio

    rig.imager.gate = asyncio.Event()
    a = await rig.svc.add(make_task("A", groups=[ExposureGroup(duration=1, count=3)]))
    c = await rig.svc.add(make_task("C"))
    b = await rig.svc.add(make_task("B", ra=10.0, dec=41.0))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.switch_to(b.task.id, "frame", actor="scheduler:test", reason="guiding stalled")
    rig.imager.gate.set()
    await wait_until(lambda: rig.svc.status().current_task_id == c.task.id)
    await rig.svc.wait_idle()

    rt_a = (await rig.svc.get(a.task.id)).runtime
    assert rt_a.status == TaskStatus.INTERRUPTED
    assert rt_a.frames_done() == 1
    assert rt_a.interruptions[-1].kind == "switch"
    assert rt_a.interruptions[-1].actor == "scheduler:test"
    # B ran right after the switch, then C; A was not picked again in this run
    order = [e.task_id for e in rig.of("sequencer.task_started")]
    assert order == [a.task.id, b.task.id, c.task.id]
    assert len(rig.of("sequencer.session_started")) == 1


async def test_switch_to_when_idle_starts_only_that_task(rig: Rig) -> None:
    await rig.svc.add(make_task("A"))
    b = await rig.svc.add(make_task("B"))
    await rig.svc.switch_to(b.task.id)
    await rig.svc.wait_idle()
    started = [e.task_id for e in rig.of("sequencer.task_started")]
    assert started == [b.task.id]


async def test_wait_for_task(rig: Rig) -> None:
    import asyncio

    a = await rig.svc.add(make_task("A"))
    b = await rig.svc.add(make_task("B"))
    waiter = asyncio.create_task(rig.svc.wait_for_task(b.task.id))
    await rig.svc.start()
    rt = await asyncio.wait_for(waiter, 3)
    assert rt.status == TaskStatus.COMPLETED
    assert (await rig.svc.get(a.task.id)).runtime.status == TaskStatus.COMPLETED


async def test_subscribe_yields_sequencer_events(rig: Rig) -> None:
    import asyncio

    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    seen: list[str] = []

    async def consume() -> None:
        async for event in rig.svc.subscribe():
            seen.append(event.type)
            if event.type == "sequencer.session_finished":
                return

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await rig.svc.start()
    await asyncio.wait_for(consumer, 3)
    assert "sequencer.frame_saved" in seen
    assert all(t.startswith("sequencer.") for t in seen)


# ── Meridian flip ─────────────────────────────────────────────────────────────


async def test_flip_when_past_threshold(rig: Rig) -> None:
    rig.mount.set_ha(0.3)
    rig.mount.pier = "West"
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=2)]))
    await _run_to_end(rig)
    assert rig.mount.flips == 1
    assert len(rig.solver.calls) == 2  # setup + after the flip
    assert rig.guider.guides == 2


async def test_no_flip_on_normal_side(rig: Rig) -> None:
    rig.mount.set_ha(0.3)
    rig.mount.pier = "East"
    await rig.svc.add(make_task())
    await _run_to_end(rig)
    assert rig.mount.flips == 0


async def test_waits_for_flip_instead_of_crossing_it(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "FLIP_POLL_S", 0.02)
    # 36 s before the flip point, HA racing at 0.01 h/s: the flip point arrives in ~0.36 s
    rig.mount.set_ha(0.09, speed=0.01)
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=60, count=1)], center=False))
    await _run_to_end(rig)
    assert rig.mount.flips == 1
    # The exposure started only after the flip
    assert rig.mount.events.index("flip") > rig.mount.events.index("slew")
    waits = [e for e in rig.of("sequencer.status") if e.status.activity == "waiting"]
    assert waits and "meridian flip" in (waits[0].status.message or "")


async def test_flip_disabled(tmp_path: Path) -> None:
    rig = Rig(tmp_path, SequencerSettings(meridian_flip_enabled=False))
    rig.mount.set_ha(0.3)
    await rig.svc.add(make_task())
    await _run_to_end(rig)
    assert rig.mount.flips == 0


async def test_frames_carry_guiding_stats(rig: Rig) -> None:
    rig.guider.unguided_s = 12.5
    rig.guider.losses = 1
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    await _run_to_end(rig)
    frame = rig.of("sequencer.frame_saved")[0]
    assert (frame.guide_rms_total, frame.unguided_s, frame.guiding_losses) == (0.8, 12.5, 1)


async def test_frames_without_guider_have_no_guiding_stats(rig: Rig) -> None:
    rig.app.state.guider = None
    await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=1)]))
    await _run_to_end(rig)
    frame = rig.of("sequencer.frame_saved")[0]
    assert frame.unguided_s is None
