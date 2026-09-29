"""Autofocus triggers and runs for the sequencer.

Autofocus runs at the task start, after a filter change, after a meridian flip (per the
task / lane / settings), and when the focuser temperature or the elapsed time since the
last autofocus crosses the configured thresholds. A run that finds no stars is an
autofocus stall: imaging carries on at the last good focus (the autofocus engine puts the
focuser back) and autofocus is retried every ``autofocus_retry_interval_s``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from astrolol.core.sequencer.models import QueueEntry, StallKind
from plugins.sequencer.stalls import StallTracker
from plugins.sequencer.steps import StepError

if TYPE_CHECKING:
    from plugins.sequencer.runner import Runner, _TaskState


async def run_autofocus(runner: Runner, entry: QueueEntry, ts: _TaskState, reason: str) -> None:
    devices = ts.devices
    assert devices is not None
    cfg = runner.settings
    if ts.af_tracker is None:
        ts.af_tracker = StallTracker(runner, entry, StallKind.AUTOFOCUS)
    tracker: StallTracker = ts.af_tracker
    try:
        ran = await runner._steps.autofocus(entry.task, devices, reason)
    except StepError as exc:
        if exc.stall_kind != StallKind.AUTOFOCUS:
            raise
        await tracker.attempt(str(exc), cfg.autofocus_retry_interval_s)
        tracker.check_timeout()
        ts.af_retry_at = time.monotonic() + cfg.autofocus_retry_interval_s
        return
    ts.af_retry_at = None
    if not ran:
        return
    if tracker.stalled:
        await tracker.recovered()
    if runner._run is not None and devices.focuser_id is not None:
        temp = await runner._steps.focuser_temperature(devices.focuser_id)
        runner._run.af_last[devices.focuser_id] = (time.monotonic(), temp)


async def autofocus_triggers(runner: Runner, entry: QueueEntry, ts: _TaskState) -> None:
    """Run autofocus now if something asks for it (called before each frame)."""
    devices = ts.devices
    if devices is None or devices.focuser_id is None or runner._run is None:
        ts.af_due = None
        return
    if getattr(runner.app.state, "autofocus_engine", None) is None:
        ts.af_due = None
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

    reason = ts.af_due
    if reason is None and ts.af_retry_at is not None and now >= ts.af_retry_at:
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
    ts.af_due = None
    await run_autofocus(runner, entry, ts, reason)
