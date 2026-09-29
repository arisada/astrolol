"""Autofocus triggers and runs for the sequencer, per lane (each lane has its own focuser).

Autofocus runs at the task start, after a filter change, after a meridian flip (per the
task / lane / settings), and when the focuser temperature or the elapsed time since the
last autofocus crosses the configured thresholds. A run that finds no stars is an
autofocus stall: imaging carries on at the last good focus (the autofocus engine puts the
focuser back) and autofocus is retried every ``autofocus_retry_interval_s``.

The autofocus engine runs one autofocus at a time: lanes take turns (``runner.af_lock``).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from astrolol.core.sequencer.models import Activity, QueueEntry, StallKind
from plugins.sequencer.devices import LaneDevices
from plugins.sequencer.stalls import StallTracker
from plugins.sequencer.steps import StepError

if TYPE_CHECKING:
    from plugins.sequencer.runner import Runner, _LaneState


async def run_autofocus(
    runner: Runner,
    entry: QueueEntry,
    ls: _LaneState,
    devices: LaneDevices,
    reason: str,
    lane_index: int = 0,
) -> None:
    cfg = runner.settings
    if ls.af_tracker is None:
        ls.af_tracker = StallTracker(runner, entry, StallKind.AUTOFOCUS)
    tracker: StallTracker = ls.af_tracker
    if lane_index:
        await runner.set_lane_activity(entry, lane_index, Activity.FOCUSING)
    try:
        async with runner.af_lock:
            ran = await runner._steps.autofocus(entry.task, devices, reason)
    except StepError as exc:
        if exc.stall_kind != StallKind.AUTOFOCUS:
            raise
        await tracker.attempt(str(exc), cfg.autofocus_retry_interval_s)
        tracker.check_timeout()
        ls.af_retry_at = time.monotonic() + cfg.autofocus_retry_interval_s
        return
    ls.af_retry_at = None
    if not ran:
        return
    if tracker.stalled:
        await tracker.recovered()
    if runner._run is not None and devices.focuser_id is not None:
        temp = await runner._steps.focuser_temperature(devices.focuser_id)
        runner._run.af_last[devices.focuser_id] = (time.monotonic(), temp)


async def autofocus_triggers(
    runner: Runner,
    entry: QueueEntry,
    ls: _LaneState,
    devices: LaneDevices,
    lane_index: int = 0,
) -> None:
    """Run autofocus on this lane now if something asks for it (called before each frame)."""
    if devices.focuser_id is None or runner._run is None:
        ls.af_due = None
        return
    if getattr(runner.app.state, "autofocus_engine", None) is None:
        ls.af_due = None
        return
    cfg = runner.settings
    now = time.monotonic()
    last = runner._run.af_last.get(devices.focuser_id)
    temp: float | None = None
    if last is None or cfg.autofocus_on_temp_delta is not None:
        temp = await runner._steps.focuser_temperature(devices.focuser_id)
    if last is None:  # baseline for the time / temperature triggers
        last = (now, temp)
        runner._run.af_last[devices.focuser_id] = last
    last_at, last_temp = last

    reason = ls.af_due
    if reason is None and ls.af_retry_at is not None and now >= ls.af_retry_at:
        reason = "retry"
    every = cfg.autofocus_every_min
    if reason is None and every is not None and now - last_at >= every * 60:
        reason = f"{every:g} min since the last one"
    delta = cfg.autofocus_on_temp_delta
    if (
        reason is None
        and delta is not None
        and temp is not None
        and last_temp is not None
        and abs(temp - last_temp) >= delta
    ):
        reason = f"temperature {last_temp:.1f} → {temp:.1f} °C"
    if reason is None:
        return
    ls.af_due = None
    await run_autofocus(runner, entry, ls, devices, reason, lane_index)
