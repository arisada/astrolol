"""Guiding supervision and centering retries — the sequencer side of sky problems.

``ensure_guiding`` runs before every frame (and in the task setup and after a flip): it
returns once guiding has been healthy for ``guide_healthy_after_s``. While guiding is
down it holds new frames (an exposure in progress is never interrupted), reports a
guiding stall, restarts guiding every ``guide_retry_interval_s`` when the guider stopped
or is disconnected, and re-centres once after ``recenter_after_guide_loss_min``. A stall is
reported when a restart fails, or when the star has been lost for longer than the retry
interval while the guider keeps trying.

``center_with_retries`` retries centering while nothing solves (clouds, obstruction).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog

from astrolol.core.sequencer.models import Activity, QueueEntry, StallKind
from plugins.sequencer.stalls import StallTracker
from plugins.sequencer.steps import StepError

if TYPE_CHECKING:
    from plugins.sequencer.runner import Runner, _TaskState

logger = structlog.get_logger()

POLL_S = 1.0  # how often guiding health is re-checked while waiting (patched in tests)


def _fmt(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 90 else f"{seconds / 60:.0f} min"


async def ensure_guiding(runner: Runner, entry: QueueEntry, ts: _TaskState) -> None:
    task = entry.task
    guider: Any = getattr(runner.app.state, "guider", None)
    if not task.start_guiding:
        return
    if guider is None:
        return  # no guider plugin: reported as a skipped step by start_guiding / pre-flight
    cfg = runner.settings
    tracker = StallTracker(runner, entry, StallKind.GUIDING)
    next_attempt = 0.0
    recentered = False
    was_connected: bool | None = None
    restarted = False
    while True:
        runner._check_boundary()
        status = guider.status()
        if status.connected and was_connected is False:
            next_attempt = 0.0  # the guider just came back: try now, not at the next retry
        was_connected = status.connected
        health = guider.health()
        if health.guiding:
            if (health.guiding_for_s or 0.0) >= cfg.guide_healthy_after_s:
                break
            await runner.set_activity(
                Activity.WAITING_FOR_GUIDING, "Waiting for guiding to stabilise"
            )
            await asyncio.sleep(POLL_S)
            continue

        unguided = health.unguided_for_s or 0.0
        if not status.connected:
            why = f"guider ({guider.name}) not connected"
        elif not status.active:
            why = "guiding stopped"
        else:
            why = (health.reason or "star lost").replace("_", " ")
        # A short loss (a cloud passing) is not a stall; a failed restart or a loss lasting
        # longer than the retry interval is.
        if status.active and unguided >= cfg.guide_retry_interval_s:
            await tracker.begin(why)
        tracker.check_timeout()
        await runner.set_activity(
            Activity.WAITING_FOR_GUIDING, f"Waiting for guiding — {why} ({_fmt(unguided)})"
        )

        needs_restart = not status.connected or not status.active
        long_loss = unguided >= cfg.recenter_after_guide_loss_min * 60
        needs_recenter = long_loss and not recentered and task.center and _has_coords(ts)
        now = time.monotonic()
        if now >= next_attempt and (needs_restart or needs_recenter):
            next_attempt = now + cfg.guide_retry_interval_s
            error: str | None = None
            try:
                if needs_recenter:
                    recentered = True
                    await runner._steps.stop_guiding(task.id)
                    assert ts.target is not None and ts.devices is not None
                    # the re-centering slews: wait until no secondary lane is exposing
                    from plugins.sequencer.lanes import mount_operation

                    await mount_operation(
                        runner,
                        entry,
                        ts,
                        "re-centering",
                        runner._steps.center(task, ts.target, ts.devices),
                    )
                await runner._steps.start_guiding(task.id)
            except StepError as exc:
                error = str(exc)
            await tracker.attempt(error, cfg.guide_retry_interval_s)
            if error is None:
                restarted = True
                continue
        await asyncio.sleep(POLL_S)

    stalled = tracker.stalled
    if stalled:
        await tracker.recovered()
    if restarted or stalled:
        ts.frames_since_dither = (
            0  # guiding restarted on a freshly selected star: counts as a dither
        )


async def wait_guiding_healthy(runner: Runner, entry: QueueEntry, lane_index: int) -> bool:
    """Secondary lanes: wait until guiding is healthy (the primary lane runs the recovery).

    Returns False if a frame-boundary request arrived while waiting.
    """
    guider: Any = getattr(runner.app.state, "guider", None)
    if not entry.task.start_guiding or guider is None:
        return True
    cfg = runner.settings
    while True:
        if runner.pending_frame_request() is not None:
            return False
        health = guider.health()
        if health.guiding and (health.guiding_for_s or 0.0) >= cfg.guide_healthy_after_s:
            return True
        await runner.set_lane_activity(entry, lane_index, Activity.WAITING_FOR_GUIDING)
        await asyncio.sleep(POLL_S)


async def center_with_retries(runner: Runner, entry: QueueEntry, ts: _TaskState) -> None:
    """Center, retrying every center_retry_interval_s while plate solving finds nothing."""
    task = entry.task
    assert ts.target is not None and ts.devices is not None
    cfg = runner.settings
    tracker = StallTracker(runner, entry, StallKind.CENTERING)
    while True:
        try:
            await runner._steps.center(task, ts.target, ts.devices)
            break
        except StepError as exc:
            if exc.stall_kind != StallKind.CENTERING:
                raise
            await tracker.attempt(str(exc), cfg.center_retry_interval_s)
            tracker.check_timeout()
            await runner._sleep(
                cfg.center_retry_interval_s,
                Activity.WAITING,
                f"Centering found no stars — retrying in {_fmt(cfg.center_retry_interval_s)}",
            )
    await tracker.recovered()


def _has_coords(ts: _TaskState) -> bool:
    return ts.target is not None and ts.target.ra is not None
