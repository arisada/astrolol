"""Parallel lanes: several cameras imaging the same target, one of them (lanes[0]) primary.

The primary lane drives every mount operation during imaging (dithers, meridian flips,
guiding recovery). Secondary lanes never touch the mount: they only start an exposure
that will end before the next mount operation the primary can perform (the *fit rule*),
and otherwise wait (``WAITING_FOR_PRIMARY``). ``RigSchedule`` holds what that needs.

Boundaries: at a frame boundary with a pause/stop/skip/switch pending, each lane stops on
its own (a lane never cancels another lane's exposure); once every lane has stopped the
request takes effect. "now" requests cancel the whole task body, i.e. every lane.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel

from astrolol.core.sequencer.events import (
    SequencerFrameDiscarded,
    SequencerFrameSaved,
    SequencerRigWait,
)
from astrolol.core.sequencer.models import (
    Activity,
    ExposureGroup,
    ImagingTask,
    Lane,
    LaneRuntime,
    QueueEntry,
)
from astrolol.plugins.sequencer.devices import LaneDevices
from astrolol.plugins.sequencer.focusing import autofocus_triggers
from astrolol.plugins.sequencer.guiding import ensure_guiding, wait_guiding_healthy

if TYPE_CHECKING:
    from astrolol.plugins.sequencer.runner import Runner, _LaneState, _TaskState

logger = structlog.get_logger()

POLL_S = 1.0  # secondary lanes re-check the schedule this often while waiting (tests patch it)
RIG_WAIT_LOG_S = 0.5


# ── Schedule ──────────────────────────────────────────────────────────────────


class RigSchedule:
    """When the primary can next operate the mount, and which secondary lanes are busy.

    ``next_mount_op()`` is a lower bound: the primary can be late (autofocus, a slow
    download) but never early, so a secondary frame that fits never overlaps a dither.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.primary_exposure_end: float | None = None  # primary exposing until then
        self.frames_to_dither: int | None = None  # None = the primary doesn't dither
        self.upcoming: list[float] = []  # durations of the primary's next frames
        self.primary_done = False
        self.mount_busy = False  # a mount operation is running
        self.flip_at: float | None = None  # flip point (clock time), if one is coming
        self._busy: set[str] = set()
        self._running: set[str] = set()
        self._changed = asyncio.Event()

    # Primary side

    def set_primary(
        self, exposure_end: float | None, frames_to_dither: int | None, upcoming: list[float]
    ) -> None:
        self.primary_exposure_end = exposure_end
        self.frames_to_dither = frames_to_dither
        self.upcoming = upcoming
        self.notify()

    def next_mount_op(self) -> float:
        now = self._clock()
        if self.mount_busy:
            return now
        dither_at = math.inf
        if not self.primary_done and self.frames_to_dither is not None:
            if self.frames_to_dither <= 0:
                dither_at = now
            else:
                exposing = self.primary_exposure_end is not None
                base = self.primary_exposure_end if exposing else now
                assert base is not None
                after = self.frames_to_dither - (1 if exposing else 0)
                dither_at = base + sum(self.upcoming[:after])
        flip_at = self.flip_at if self.flip_at is not None else math.inf
        return min(dither_at, flip_at)

    def fits(self, duration: float, margin: float) -> bool:
        return self._clock() + duration + margin <= self.next_mount_op()

    # Secondary side

    def lane_running(self, lane_id: str, running: bool) -> None:
        (self._running.add if running else self._running.discard)(lane_id)
        self.notify()

    @property
    def secondaries_running(self) -> bool:
        return bool(self._running)

    def set_busy(self, lane_id: str, busy: bool) -> None:
        (self._busy.add if busy else self._busy.discard)(lane_id)
        self.notify()

    @property
    def secondaries_idle(self) -> bool:
        return not self._busy

    async def wait_secondaries_idle(self) -> float:
        """Wait until no secondary is exposing or focusing. Returns the seconds waited."""
        t0 = self._clock()
        while self._busy:
            await self.wait_change(POLL_S)
        return self._clock() - t0

    # Change notification

    def notify(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    async def wait_change(self, timeout: float) -> None:
        event = self._changed
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(event.wait(), timeout)


# ── Estimates (pre-flight, task editor) ───────────────────────────────────────


class LaneEstimate(BaseModel):
    lane_id: str
    primary: bool
    exposure_s: float  # total exposure planned
    efficiency: float  # fraction of the time the lane spends exposing (1.0 = never waits)
    wall_s: float  # rough duration of the lane
    can_start: bool = True  # False: an exposure is longer than the gap between two dithers
    longest_s: float = 0.0


def _weighted_primary_duration(task: ImagingTask) -> float:
    groups = task.lanes[0].groups
    frames = sum(g.count for g in groups)
    return sum(g.count * g.duration for g in groups) / frames if frames else 0.0


def estimate_lanes(task: ImagingTask, margin_s: float) -> list[LaneEstimate]:
    """Per-lane exposure, efficiency and duration, from the fit rule.

    Between two dithers the primary exposes ``dither_every`` frames. A secondary frame
    starts only if it ends ``margin`` before the dither, so (download time aside) it fits
    ``floor((interval - duration - margin) / duration) + 1`` frames per interval.

    This genuinely requires ``duration + margin <= interval`` even for a single frame —
    there's no "first frame is free" exemption, because the runtime scheduling gate this
    estimate has to match (``RigSchedule.fits()`` in this module) doesn't grant one
    either: it always requires ``clock() + duration + margin <= next_mount_op()``, with
    no notion of "this is the first secondary frame since the last dither." A secondary
    lane whose exposure is close to or equal to the primary's own, with ``dither_every``
    tight, is a real scheduling conflict, not just an overly strict estimate — the
    secondary will actually stall forever in WAITING_FOR_PRIMARY at runtime, not just get
    a pessimistic preflight number. (An earlier version of this function added that
    exemption to fix a confusing preflight warning on two equal-duration lanes, without
    changing the runtime gate to match — which made the preflight lie instead. See the
    TODO entry on parallel lanes for what a real fix — teaching the runtime gate the same
    "first frame since the last dither is free" rule — would need.)
    """
    primary = task.lanes[0]
    primary_total = sum(g.count * g.duration for g in primary.groups)
    out = [
        LaneEstimate(
            lane_id=primary.id,
            primary=True,
            exposure_s=primary_total,
            efficiency=1.0,
            wall_s=primary_total,
            longest_s=max((g.duration for g in primary.groups), default=0.0),
        )
    ]
    dither_every = task.dither_every
    interval = _weighted_primary_duration(task) * dither_every if dither_every else None
    shortest_interval = (
        min(g.duration for g in primary.groups) * dither_every if dither_every else None
    )
    for lane in task.lanes[1:]:
        total = sum(g.count * g.duration for g in lane.groups)
        longest = max((g.duration for g in lane.groups), default=0.0)
        if interval is None or interval <= 0:
            out.append(
                LaneEstimate(
                    lane_id=lane.id,
                    primary=False,
                    exposure_s=total,
                    efficiency=1.0,
                    wall_s=total,
                    longest_s=longest,
                )
            )
            continue
        exposing = 0.0
        for g in lane.groups:
            room = interval - g.duration - margin_s
            per_interval = math.floor(room / g.duration) + 1 if room >= 0 else 0
            eff = per_interval * g.duration / interval
            exposing += g.count * g.duration * eff
        efficiency = exposing / total if total else 1.0
        can_start = shortest_interval is not None and all(
            g.duration + margin_s <= shortest_interval for g in lane.groups
        )
        wall = total / efficiency if efficiency > 0 else math.inf
        out.append(
            LaneEstimate(
                lane_id=lane.id,
                primary=False,
                exposure_s=total,
                efficiency=round(efficiency, 3),
                wall_s=round(wall, 1) if math.isfinite(wall) else 1e12,
                can_start=can_start,
                longest_s=longest,
            )
        )
    return out


# ── Running the lanes ─────────────────────────────────────────────────────────


async def run_lanes(runner: Runner, entry: QueueEntry, ts: _TaskState) -> None:
    """Run every lane of the task; returns when all are done or all stopped at a boundary."""
    from astrolol.plugins.sequencer.runner import _BoundaryReached

    task = entry.task
    if ts.schedule is None:
        ts.schedule = RigSchedule()
    schedule: RigSchedule = ts.schedule
    schedule.primary_done = False
    schedule.mount_busy = False

    async def guarded(coro: Any) -> None:
        # A lane stopped at its boundary: the others finish their frame.
        with contextlib.suppress(_BoundaryReached):
            await coro

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(guarded(primary_lane(runner, entry, ts, task.lanes[0])))
            for idx, lane in enumerate(task.lanes[1:], start=1):
                schedule.lane_running(lane.id, True)
                tg.create_task(guarded(secondary_lane(runner, entry, ts, lane, idx)))
    except BaseExceptionGroup as group:
        # A lane failed (the others were cancelled): surface that error as is, so the
        # task's error policy sees a StepError, not a group.
        raise _first_error(group) from None

    req = runner.pending_frame_request()
    if req is not None and any(next_group_of(entry, ts, lane) is not None for lane in task.lanes):
        raise _BoundaryReached(req)


def _first_error(group: BaseExceptionGroup) -> BaseException:
    for exc in group.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            return _first_error(exc)
        if not isinstance(exc, asyncio.CancelledError):
            return exc
    return group.exceptions[0]


def next_group_of(entry: QueueEntry, ts: _TaskState, lane: Lane) -> int | None:
    from astrolol.plugins.sequencer.runner import _LaneState, lane_runtime, next_group

    ls = ts.lanes.setdefault(lane.id, _LaneState())
    return next_group(lane, lane_runtime(entry, lane.id), ls, peek=True)


def _upcoming(lane: Lane, lrt: LaneRuntime, ls: _LaneState, n: int) -> list[float]:
    """Durations of the lane's next *n* frames (simulated on copies)."""
    from astrolol.plugins.sequencer.runner import next_group

    lrt_copy = lrt.model_copy(deep=True)
    ls_copy = type(ls)(current_filter=ls.current_filter, rr_group=ls.rr_group, rr_taken=ls.rr_taken)
    out: list[float] = []
    for _ in range(n):
        gidx = next_group(lane, lrt_copy, ls_copy)
        if gidx is None:
            break
        out.append(lane.groups[gidx].duration)
        lrt_copy.groups[gidx].frames_done += 1
        if lane.order == "round_robin":
            ls_copy.rr_taken += 1
    return out


def _publish_primary_plan(
    entry: QueueEntry, ts: _TaskState, lane: Lane, exposure_end: float | None
) -> None:
    """Tell the schedule when the primary will next dither."""
    from astrolol.plugins.sequencer.runner import _LaneState, lane_runtime

    schedule: RigSchedule = ts.schedule
    task = entry.task
    if not task.dither_every:
        schedule.set_primary(exposure_end, None, [])
        return
    frames_to_dither = task.dither_every - ts.frames_since_dither
    ls = ts.lanes.setdefault(lane.id, _LaneState())
    lrt = lane_runtime(entry, lane.id)
    # Progress is recorded after a frame, so while exposing the first "upcoming" frame is
    # the one in flight: drop it.
    upcoming = _upcoming(lane, lrt, ls, max(0, frames_to_dither))
    if exposure_end is not None and upcoming:
        upcoming = upcoming[1:]
    schedule.set_primary(exposure_end, frames_to_dither, upcoming)


async def primary_lane(runner: Runner, entry: QueueEntry, ts: _TaskState, lane: Lane) -> None:
    from astrolol.plugins.sequencer.runner import _LaneState, lane_runtime, next_group

    task = entry.task
    devices = ts.lane_devices[lane.id]
    lrt = lane_runtime(entry, lane.id)
    ls = ts.lanes.setdefault(lane.id, _LaneState())
    schedule: RigSchedule = ts.schedule
    try:
        while True:
            gidx = next_group(lane, lrt, ls)
            if gidx is None:
                break
            group = lane.groups[gidx]
            runner._check_boundary()
            _publish_primary_plan(entry, ts, lane, None)
            await runner._maybe_flip(entry, ts, group.duration)
            await _prepare_frame(runner, entry, ts, lane, ls, devices, group, index=0)
            await ensure_guiding(runner, entry, ts)
            runner._check_boundary()
            lrt.current_group = gidx
            end = time.monotonic() + group.duration
            _publish_primary_plan(entry, ts, lane, end)
            try:
                await expose_and_record(
                    runner, entry, ts, lane, 0, gidx, group, devices, primary=True
                )
            finally:
                _publish_primary_plan(entry, ts, lane, None)

            if next_group(lane, lrt, ls, peek=True) is None:
                break
            runner._check_boundary()
            if task.dither_every and ts.frames_since_dither >= task.dither_every:
                await mount_operation(runner, entry, ts, "dither", runner._steps.dither(task.id))
                ts.frames_since_dither = 0
                _publish_primary_plan(entry, ts, lane, None)
            if task.sub_delay_s > 0:
                await runner._sleep(task.sub_delay_s, Activity.WAITING, "Waiting between frames")
    finally:
        schedule.primary_done = True
        schedule.notify()
    await primary_duties(runner, entry, ts)


async def primary_duties(runner: Runner, entry: QueueEntry, ts: _TaskState) -> None:
    """The primary has finished its plan but secondaries still image: keep owning the mount
    (meridian flip, guiding recovery) until they are done."""
    schedule: RigSchedule = ts.schedule
    if not schedule.secondaries_running:
        return
    await runner.set_activity(Activity.WAITING, "Primary done — waiting for the other cameras")
    while schedule.secondaries_running:
        runner._check_boundary()
        await runner._maybe_flip(entry, ts, 0.0)
        if entry.task.start_guiding and getattr(runner.app.state, "guider", None) is not None:
            health = runner.app.state.guider.health()
            if not health.guiding:
                await ensure_guiding(runner, entry, ts)
        await schedule.wait_change(POLL_S)


async def mount_operation(
    runner: Runner, entry: QueueEntry, ts: _TaskState, what: str, op: Any
) -> Any:
    """Run a primary mount operation once every secondary lane is idle."""
    schedule: RigSchedule | None = ts.schedule
    if schedule is None:
        return await op
    schedule.mount_busy = True
    schedule.notify()
    try:
        waited = await schedule.wait_secondaries_idle()
        if waited >= RIG_WAIT_LOG_S:
            await runner.bus.publish(
                SequencerRigWait(
                    task_id=entry.task.id,
                    lane_id=entry.task.lanes[0].id,
                    waited_for=f"secondaries before {what}",
                    duration_s=round(waited, 1),
                )
            )
            logger.info(
                "sequencer.rig_wait",
                task_id=entry.task.id,
                waited_for=what,
                duration_s=round(waited, 1),
            )
        return await op
    finally:
        schedule.mount_busy = False
        schedule.notify()


async def secondary_lane(
    runner: Runner, entry: QueueEntry, ts: _TaskState, lane: Lane, index: int
) -> None:
    from astrolol.plugins.sequencer.runner import _LaneState, lane_runtime, next_group

    devices = ts.lane_devices[lane.id]
    lrt = lane_runtime(entry, lane.id)
    ls = ts.lanes.setdefault(lane.id, _LaneState())
    schedule: RigSchedule = ts.schedule
    margin = runner.settings.download_margin_s
    try:
        while True:
            gidx = next_group(lane, lrt, ls)
            if gidx is None:
                return
            group = lane.groups[gidx]
            if runner.pending_frame_request() is not None:
                return
            await _prepare_frame(runner, entry, ts, lane, ls, devices, group, index=index)
            # Guiding healthy and the frame fits before the next mount operation
            while True:
                if runner.pending_frame_request() is not None:
                    return
                if not await wait_guiding_healthy(runner, entry, index):
                    return
                if schedule.fits(group.duration, margin):
                    break
                await runner.set_lane_activity(entry, index, Activity.WAITING_FOR_PRIMARY)
                await schedule.wait_change(POLL_S)
            lrt.current_group = gidx
            await expose_and_record(
                runner, entry, ts, lane, index, gidx, group, devices, primary=False
            )
    finally:
        schedule.lane_running(lane.id, False)
        await runner.set_lane_activity(entry, index, None)


async def _prepare_frame(
    runner: Runner,
    entry: QueueEntry,
    ts: _TaskState,
    lane: Lane,
    ls: _LaneState,
    devices: LaneDevices,
    group: ExposureGroup,
    index: int,
) -> None:
    """Filter change (and the autofocus it may trigger) before a lane's next frame."""
    schedule: RigSchedule = ts.schedule
    if group.filter_name is not None and ls.current_filter != group.filter_name:
        if index:
            await runner.set_lane_activity(entry, index, Activity.CHANGING_FILTER)
        moved = await runner._steps.change_filter(entry.task.id, devices, group.filter_name)
        ls.current_filter = group.filter_name
        # Only moved==True means the wheel actually turned. ls.current_filter gets
        # invalidated on every sequencer resume (a pause could have let something else
        # touch the wheel) even when it didn't — don't autofocus for those no-ops.
        if moved and lane.autofocus_on_filter_change:
            ls.af_due = f"filter {group.filter_name}"
    if index:
        schedule.set_busy(lane.id, True)
    try:
        await autofocus_triggers(runner, entry, ls, devices, lane_index=index)
    finally:
        if index:
            schedule.set_busy(lane.id, False)


async def expose_and_record(
    runner: Runner,
    entry: QueueEntry,
    ts: _TaskState,
    lane: Lane,
    index: int,
    gidx: int,
    group: ExposureGroup,
    devices: LaneDevices,
    *,
    primary: bool,
) -> None:
    """Expose one frame on the lane's camera and record it (progress, events, FITS cards)."""
    from astrolol.plugins.sequencer.runner import _LaneState, lane_runtime

    task = entry.task
    lrt = lane_runtime(entry, lane.id)
    ls = ts.lanes.setdefault(lane.id, _LaneState())
    schedule: RigSchedule = ts.schedule
    done = lrt.groups[gidx].frames_done
    label = f"{group.filter_name} " if group.filter_name else ""
    message = f"Exposing {label}{done + 1}/{group.count} ({group.duration:g} s)"
    if primary:
        runner.exposure_started(group.duration)
        await runner.set_activity(Activity.EXPOSING, message)
    else:
        schedule.set_busy(lane.id, True)
        await runner.set_lane_activity(entry, index, Activity.EXPOSING)
    guide_mark = runner._steps.guiding_mark()
    try:
        fits_path = await runner._steps.expose(task, devices, group)
    except asyncio.CancelledError:
        await runner.bus.publish(
            SequencerFrameDiscarded(
                task_id=task.id,
                lane_id=lane.id,
                group_idx=gidx,
                reason="exposure aborted",
            )
        )
        raise
    finally:
        if primary:
            runner.exposure_started(None)
        else:
            schedule.set_busy(lane.id, False)

    guiding = runner._steps.guiding_stats(guide_mark)
    await runner._steps.record_guiding_in_fits(fits_path, guiding)
    limit = runner.settings.uncount_if_unguided_s
    unguided = guiding.get("unguided_s")
    counted = limit is None or unguided is None or unguided <= limit
    if counted:
        lrt.groups[gidx].frames_done += 1
        if lane.order == "round_robin":
            ls.rr_taken += 1
    else:
        logger.warning(
            "sequencer.frame_not_counted",
            task_id=task.id,
            fits_path=fits_path,
            unguided_s=unguided,
            limit_s=limit,
        )
    runner.frame_saved()
    await runner.bus.publish(
        SequencerFrameSaved(
            task_id=task.id,
            lane_id=lane.id,
            camera_id=devices.camera_id,
            group_idx=gidx,
            frame_idx=done,
            frames_total=group.count,
            filter_name=group.filter_name,
            duration=group.duration,
            fits_path=fits_path,
            counted=counted,
            object_name=task.target.name,
            **await runner._steps.frame_context(devices),
            **guiding,
        )
    )
    await runner.commit()
    if primary:
        ts.frames_since_dither += 1
