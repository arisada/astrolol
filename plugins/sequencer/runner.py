"""Runner — executes the queue: one asyncio task per run, one inner task per task body.

Control model
-------------
Every control request (pause, stop, skip, switch, cancel) carries a boundary:

- ``frame``/``task``: stored in ``_request``; the task body checks it at each frame
  boundary (raising ``_BoundaryReached``), the run loop at each task boundary.
- ``now``: stored the same way, and the inner task-body task is cancelled, which aborts the
  in-flight exposure (the frame is discarded).

After a boundary, ``_execute`` decides what happens to the current task. Pausing keeps the
task RUNNING; resuming re-enters the task body, re-running setup (slew/center/guide) only
when needed. Stopping or switching leaves the task INTERRUPTED with its progress.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

import structlog

from astrolol.core.sequencer.errors import (
    InvalidRequest,
    PreflightFailed,
    SequencerBusy,
    SequencerNotRunning,
)
from astrolol.core.sequencer.events import (
    SequencerInterruption,
    SequencerResumed,
    SequencerSessionFinished,
    SequencerSessionStarted,
    SequencerStatusChanged,
    SequencerStepFailed,
    SequencerTaskFinished,
    SequencerTaskStarted,
)
from astrolol.core.sequencer.models import (
    Activity,
    Actor,
    Boundary,
    Interruption,
    Lane,
    LaneRuntime,
    QueueEntry,
    RunOutcome,
    RunState,
    SequencerStatus,
    TaskStatus,
)
from astrolol.mount.manager import meridian_flip_due
from plugins.sequencer.devices import LaneDevices, resolve_lane_devices, run_mount_id
from plugins.sequencer.focusing import run_autofocus
from plugins.sequencer.guiding import center_with_retries, ensure_guiding
from plugins.sequencer.lanes import mount_operation, run_lanes
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.steps import StepError, Steps
from plugins.sequencer.targets import ResolvedTarget

if TYPE_CHECKING:
    from plugins.sequencer.service import SequencerServiceImpl

logger = structlog.get_logger()

SIDEREAL_RATE = 1.0027379  # hour angle advances this many hours per solar hour
FLIP_LOOKAHEAD_MARGIN_S = 30.0  # download + overhead allowed after an exposure
FLIP_POLL_S = 2.0  # mount polling interval while waiting for the flip point
MAX_INTERRUPTIONS = 50
RUNNABLE = (TaskStatus.PENDING, TaskStatus.INTERRUPTED)
SWITCHABLE = (TaskStatus.PENDING, TaskStatus.INTERRUPTED, TaskStatus.FAILED, TaskStatus.SKIPPED)

RequestKind = Literal["pause", "stop", "skip", "switch", "cancel"]
_PRIORITY: dict[str, int] = {"pause": 0, "skip": 1, "switch": 1, "stop": 2, "cancel": 3}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Request:
    kind: RequestKind
    when: Boundary
    actor: Actor
    reason: str | None = None
    task_id: str | None = None  # switch target

    @property
    def label(self) -> str:
        return f"{self.kind}@{self.when}"


class _BoundaryReached(Exception):
    def __init__(self, request: _Request) -> None:
        super().__init__(request.label)
        self.request = request


class _AbortRun(Exception):
    pass


@dataclass
class _LaneState:
    current_filter: str | None = None
    rr_group: int | None = None
    rr_taken: int = 0
    af_due: str | None = None  # autofocus requested before the next frame (reason)
    af_retry_at: float | None = None  # monotonic time to retry a failed autofocus
    af_tracker: Any = None  # StallTracker for autofocus stalls


@dataclass
class _TaskState:
    """In-memory state of a task within one run."""

    lanes: dict[str, _LaneState] = field(default_factory=dict)
    frames_since_dither: int = 0
    setup_done: bool = False
    flipped: bool = False
    target: ResolvedTarget | None = None
    devices: LaneDevices | None = None  # the primary lane's devices (mount, centering camera)
    lane_devices: dict[str, LaneDevices] = field(default_factory=dict)
    schedule: Any = None  # lanes.RigSchedule


@dataclass
class _Run:
    actor: Actor
    only: set[str] | None
    excluded: set[str]
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    forced_next: str | None = None
    frames_saved: int = 0
    tasks: dict[str, _TaskState] = field(default_factory=dict)
    # focuser_id → (monotonic time, focuser temperature) of the last autofocus (or the
    # baseline when none ran yet this run) — for the time / temperature triggers
    af_last: dict[str, tuple[float, float | None]] = field(default_factory=dict)


@dataclass
class _Outcome:
    """Result of executing one task: continue with the next task, or end the run."""

    end_run: bool = False
    run_outcome: RunOutcome = RunOutcome.STOPPED


class Runner:
    def __init__(self, service: SequencerServiceImpl) -> None:
        self._svc = service
        self.app: Any = service.app
        self.bus: Any = service.bus
        self._steps = Steps(self)

        self._run: _Run | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._exec_task: asyncio.Task[None] | None = None
        self._request: _Request | None = None
        self._resume_requested = False
        self._resume_actor: Actor = "api"
        self._wake = asyncio.Event()

        self._state = RunState.IDLE
        self._activity: Activity | None = None
        self._message: str | None = None
        self._current: QueueEntry | None = None
        self._pause_reason: str | None = None
        self._last_outcome: RunOutcome | None = None
        self._last_error: str | None = None
        self._exposure_started_at: datetime | None = None
        self._exposure_duration: float | None = None
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self.af_lock = asyncio.Lock()  # the autofocus engine runs one autofocus at a time

    # ── StepHost ───────────────────────────────────────────────────────────

    @property
    def settings(self) -> SequencerSettings:
        return self._svc.settings

    async def set_activity(self, activity: Activity | None, message: str | None) -> None:
        self._activity = activity
        self._message = message
        if self._current is not None and self._current.runtime.lanes:
            self._current.runtime.lanes[0].activity = activity
        await self.emit_status()

    # ── Status ─────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._run_task is not None and not self._run_task.done()

    @property
    def current_task_id(self) -> str | None:
        return self._current.task.id if self._current is not None else None

    def status(self) -> SequencerStatus:
        entries = self._svc.entries
        cur = self._current
        return SequencerStatus(
            run_state=self._state,
            activity=self._activity,
            message=self._message,
            current_task_id=cur.task.id if cur else None,
            lanes=[lr.model_copy() for lr in cur.runtime.lanes] if cur else [],
            pause_reason=self._pause_reason,
            pending_request=self._request.label if self._request else None,
            stall=cur.runtime.stall if cur else None,
            last_run_outcome=self._last_outcome,
            last_error=self._last_error,
            session_id=self._run.session_id if self._run else None,
            tasks_total=len(entries),
            tasks_done=sum(1 for e in entries if e.runtime.status == TaskStatus.COMPLETED),
            exposure_started_at=self._exposure_started_at,
            exposure_duration=self._exposure_duration,
            eta_s=self._eta(),
        )

    def _eta(self) -> float | None:
        remaining = 0.0
        for e in self._svc.entries:
            if e.runtime.status not in (*RUNNABLE, TaskStatus.RUNNING):
                continue
            remaining += remaining_seconds(e)
        return round(remaining, 1) if remaining > 0 else None

    async def commit(self) -> None:
        """Persist and announce the queue (runtime changed)."""
        await self._svc.commit()

    async def emit_status(self) -> None:
        await self.bus.publish(SequencerStatusChanged(status=self.status()))
        self._svc.notify()

    async def _set_state(self, state: RunState) -> None:
        self._state = state
        await self.emit_status()

    # ── Control API (called by the service) ────────────────────────────────

    async def start(
        self, candidates: list[QueueEntry], excluded: set[str], only: set[str] | None, actor: Actor
    ) -> None:
        if self.is_running:
            raise SequencerBusy("The sequencer is already running")
        report = await self._svc.preflight([e.task.id for e in candidates])
        if not report.ok:
            raise PreflightFailed(report)
        self._request = None
        self._resume_requested = False
        self._last_error = None
        self._pause_reason = None
        self._run = _Run(actor=actor, only=only, excluded=excluded)
        self._idle_event.clear()
        self._state = RunState.STARTING
        self._run_task = asyncio.create_task(self._main(self._run), name="sequencer_run")
        logger.info(
            "sequencer.run_started",
            actor=actor,
            tasks=len(candidates),
            session_id=self._run.session_id,
        )

    async def request(
        self,
        kind: RequestKind,
        when: Boundary,
        actor: Actor,
        reason: str | None = None,
        task_id: str | None = None,
    ) -> None:
        if not self.is_running:
            if kind in ("stop", "cancel"):
                return  # nothing to stop — idempotent
            raise SequencerNotRunning("The sequencer is not running")
        if kind == "skip" and self._current is None:
            raise InvalidRequest("No task is running")
        if kind == "pause" and self._state == RunState.PAUSED:
            return
        existing = self._request
        if existing is not None and _PRIORITY[existing.kind] > _PRIORITY[kind]:
            logger.info("sequencer.request_ignored", kind=kind, pending=existing.label)
            return
        self._request = _Request(kind=kind, when=when, actor=actor, reason=reason, task_id=task_id)
        logger.info(
            "sequencer.request", kind=kind, when=when, actor=actor, reason=reason, task_id=task_id
        )
        if self._state not in (RunState.PAUSED, RunState.STARTING):
            if kind == "pause":
                self._state = RunState.PAUSING
            elif kind in ("stop", "cancel"):
                self._state = RunState.STOPPING
        if when == "now" and self._exec_task is not None and not self._exec_task.done():
            self._exec_task.cancel()
        self._wake.set()
        await self.emit_status()

    async def resume(self, actor: Actor) -> None:
        if not self.is_running:
            raise SequencerNotRunning("The sequencer is not running")
        if self._state == RunState.PAUSING and self._request and self._request.kind == "pause":
            # Resume before the pause took effect: just drop the pending pause.
            self._request = None
            self._state = RunState.RUNNING
            await self.emit_status()
            return
        if self._state != RunState.PAUSED:
            return
        self._resume_requested = True
        self._resume_actor = actor
        self._wake.set()

    async def wait_idle(self) -> RunOutcome | None:
        await self._idle_event.wait()
        return self._last_outcome

    async def shutdown(self) -> None:
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._run_task

    # ── Run loop ───────────────────────────────────────────────────────────

    async def _main(self, run: _Run) -> None:
        outcome = RunOutcome.COMPLETED
        error: str | None = None
        await self.bus.publish(SequencerSessionStarted(session_id=run.session_id, actor=run.actor))
        mount_id = run_mount_id(self.app)
        try:
            await self._set_state(RunState.STARTING)
            if self.settings.unpark_on_start:
                await self._steps.unpark(mount_id)
            await self._set_state(RunState.RUNNING)
            with self._auto_flip_suspended(mount_id):
                while True:
                    ended = await self._task_boundary(run)
                    if ended is not None:
                        outcome = ended
                        break
                    entry = self._next_entry(run)
                    if entry is None:
                        break
                    if remaining_frames(entry) == 0:
                        await self._finish_task(entry, TaskStatus.COMPLETED)
                        continue
                    result = await self._execute(entry, run)
                    if result.end_run:
                        outcome = result.run_outcome
                        break
            if outcome == RunOutcome.COMPLETED and self.settings.park_on_complete:
                await self._steps.park(mount_id)
        except (_AbortRun, StepError) as exc:
            outcome, error = RunOutcome.FAILED, str(exc)
        except asyncio.CancelledError:
            outcome = RunOutcome.CANCELLED
            await self._interrupt_current("cancel", "system", "sequencer shut down")
            raise
        except Exception as exc:
            logger.error("sequencer.run_crashed", error=str(exc), exc_info=True)
            outcome, error = RunOutcome.FAILED, f"Internal error: {exc}"
            await self._interrupt_current("crash", "system", error)
        finally:
            self._run = None
            self._request = None
            self._current = None
            self._activity = None
            self._message = None
            self._exposure_started_at = None
            self._exposure_duration = None
            self._pause_reason = None
            self._last_outcome = outcome
            self._last_error = error
            self._state = RunState.IDLE
            self._idle_event.set()
            await self.bus.publish(
                SequencerSessionFinished(
                    session_id=run.session_id,
                    outcome=outcome,
                    error=error,
                    frames_saved=run.frames_saved,
                )
            )
            await self.emit_status()
            logger.info(
                "sequencer.run_finished", outcome=outcome, error=error, frames=run.frames_saved
            )

    async def _task_boundary(self, run: _Run) -> RunOutcome | None:
        """Handle a request pending between tasks. Returns an outcome to end the run."""
        req = self._take_request()
        while req is not None:
            if req.kind in ("stop", "cancel"):
                await self._publish_interruption(None, req)
                return RunOutcome.CANCELLED if req.kind == "cancel" else RunOutcome.STOPPED
            if req.kind == "switch":
                run.forced_next = req.task_id
                return None
            if req.kind == "skip":
                return None  # the task it aimed at has finished already
            # pause between tasks
            await self._publish_interruption(None, req)
            self._pause_reason = "user"
            req, paused_s = await self._wait_paused()
            if req is None:
                await self.bus.publish(
                    SequencerResumed(
                        task_id=None,
                        actor=self._resume_actor,
                        paused_s=paused_s,
                        setup_rerun=False,
                    )
                )
                await self._set_state(RunState.RUNNING)
        return None

    def _next_entry(self, run: _Run) -> QueueEntry | None:
        if run.forced_next is not None:
            tid, run.forced_next = run.forced_next, None
            entry = self._svc.find(tid)
            if entry is not None and entry.runtime.status in SWITCHABLE:
                return entry
        for entry in self._svc.entries:
            tid = entry.task.id
            if entry.runtime.status not in RUNNABLE or tid in run.excluded:
                continue
            if run.only is not None and tid not in run.only:
                continue
            return entry
        return None

    # ── One task ───────────────────────────────────────────────────────────

    async def _execute(self, entry: QueueEntry, run: _Run) -> _Outcome:
        task, rt = entry.task, entry.runtime
        ts = run.tasks.setdefault(task.id, _TaskState())
        resumed = rt.status == TaskStatus.INTERRUPTED or rt.frames_done() > 0
        rt.status = TaskStatus.RUNNING
        rt.started_at = rt.started_at or _now()
        rt.finished_at = None
        rt.last_error = None
        rt.stall = None
        self._current = entry
        await self._svc.commit()
        await self.bus.publish(
            SequencerTaskStarted(task_id=task.id, name=task.display_name, resumed=resumed)
        )
        logger.info(
            "sequencer.task_started", task_id=task.id, name=task.display_name, resumed=resumed
        )

        setup_needed = True
        while True:
            request: _Request | None = None
            error: StepError | None = None
            self._exec_task = asyncio.create_task(
                self._task_body(entry, ts, setup_needed),
                name=f"sequencer_task_{task.id[:8]}",
            )
            try:
                await self._exec_task
            except _BoundaryReached as br:
                request = br.request
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise  # the whole run is being cancelled
                request = self._request or _Request(kind="cancel", when="now", actor="system")
            except StepError as exc:
                error = exc
            finally:
                self._exec_task = None
                self._exposure_started_at = None
                self._exposure_duration = None

            if request is None and error is None:
                await self._finish_task(entry, TaskStatus.COMPLETED)
                return _Outcome()

            if error is not None:
                decision = await self._on_error(entry, ts, error, run)
            else:
                assert request is not None
                if self._request is request:
                    self._request = None
                decision = await self._on_request(entry, ts, request, run)
            if isinstance(decision, _Outcome):
                return decision
            setup_needed = decision  # retry/resume the same task

    async def _on_request(
        self, entry: QueueEntry, ts: _TaskState, req: _Request, run: _Run
    ) -> _Outcome | bool:
        """Act on a request at a boundary of the current task.

        Returns an _Outcome (task done with, continue or end the run), or a bool meaning
        "re-enter the task body", with whether setup must be re-run.
        """
        task = entry.task
        if req.kind == "pause":
            await self._publish_interruption(task.id, req, record_on=entry)
            self._pause_reason = "user"
            pointing = await self._pointing()
            nreq, paused_s = await self._wait_paused()
            if nreq is None:
                return await self._resumed(entry, ts, paused_s, pointing, force_setup=False)
            return await self._on_request(entry, ts, nreq, run)

        if req.kind in ("stop", "cancel"):
            interruption = await self._publish_interruption(task.id, req)
            await self._finish_task(entry, TaskStatus.INTERRUPTED, interruption)
            return _Outcome(
                end_run=True,
                run_outcome=(RunOutcome.CANCELLED if req.kind == "cancel" else RunOutcome.STOPPED),
            )

        if req.kind == "skip":
            interruption = await self._publish_interruption(task.id, req)
            await self._finish_task(entry, TaskStatus.SKIPPED, interruption)
            return _Outcome()

        # switch
        if req.task_id == task.id:
            return False  # switching to the running task: carry on
        interruption = await self._publish_interruption(task.id, req)
        await self._finish_task(entry, TaskStatus.INTERRUPTED, interruption)
        run.excluded.add(task.id)
        run.forced_next = req.task_id
        return _Outcome()

    async def _on_error(
        self, entry: QueueEntry, ts: _TaskState, err: StepError, run: _Run
    ) -> _Outcome | bool:
        task, rt = entry.task, entry.runtime
        policy = task.on_error
        rt.last_error = str(err)
        await self.bus.publish(
            SequencerStepFailed(
                task_id=task.id,
                step=err.step,
                error=str(err),
                handling=policy,
            )
        )
        logger.warning(
            "sequencer.step_failed", task_id=task.id, step=err.step, error=str(err), handling=policy
        )

        if policy == "skip":
            await self._finish_task(entry, TaskStatus.FAILED)
            return _Outcome()
        if policy == "defer":
            interruption = Interruption(
                at=_now(),
                kind="defer",
                actor="system",
                reason=str(err),
                stall_kind=err.stall_kind,
            )
            await self.bus.publish(
                SequencerInterruption(
                    task_id=task.id,
                    kind="defer",
                    actor="system",
                    reason=str(err),
                    stall_kind=err.stall_kind,
                )
            )
            await self._finish_task(entry, TaskStatus.INTERRUPTED, interruption)
            run.excluded.add(task.id)
            return _Outcome()
        if policy == "abort":
            await self._finish_task(entry, TaskStatus.FAILED)
            raise _AbortRun(str(err))

        # pause: the task stays RUNNING; resume retries the failed step
        self._pause_reason = str(err)
        pointing = await self._pointing()
        nreq, paused_s = await self._wait_paused()
        if nreq is None:
            rt.last_error = None
            return await self._resumed(entry, ts, paused_s, pointing, force_setup=err.needs_setup)
        return await self._on_request(entry, ts, nreq, run)

    async def _resumed(
        self,
        entry: QueueEntry,
        ts: _TaskState,
        paused_s: float,
        pointing_before: tuple[float, float] | None,
        *,
        force_setup: bool,
    ) -> bool:
        moved = False
        if pointing_before is not None:
            after = await self._pointing()
            if after is not None and _separation_deg(pointing_before, after) > 0.25:
                moved = True
        setup = (
            force_setup
            or not ts.setup_done
            or moved
            or paused_s > self.settings.recenter_after_pause_min * 60
        )
        self._pause_reason = None
        await self.bus.publish(
            SequencerResumed(
                task_id=entry.task.id,
                actor=self._resume_actor,
                paused_s=round(paused_s, 1),
                setup_rerun=setup,
            )
        )
        logger.info(
            "sequencer.resumed", task_id=entry.task.id, paused_s=round(paused_s, 1), setup=setup
        )
        await self._set_state(RunState.RUNNING)
        return setup

    async def _wait_paused(self) -> tuple[_Request | None, float]:
        """Block in PAUSED until resumed (→ None) or another request arrives."""
        t0 = time.monotonic()
        self._resume_requested = False
        await self.set_activity(None, "Paused")
        await self._set_state(RunState.PAUSED)
        while True:
            req = self._take_request()
            if req is not None and req.kind != "pause":
                return req, time.monotonic() - t0
            if self._resume_requested:
                self._resume_requested = False
                return None, time.monotonic() - t0
            self._wake.clear()
            await self._wake.wait()

    def _take_request(self) -> _Request | None:
        req, self._request = self._request, None
        return req

    # ── Task body ──────────────────────────────────────────────────────────

    async def _task_body(self, entry: QueueEntry, ts: _TaskState, setup_needed: bool) -> None:
        task = entry.task
        ts.lane_devices = {}
        for lane in task.lanes:
            devices = resolve_lane_devices(self.app, lane)
            if devices.camera_id is None:
                raise StepError("expose", f"Camera '{lane.camera_id or 'main'}' is not connected")
            ts.lane_devices[lane.id] = devices
        ts.devices = ts.lane_devices[task.lanes[0].id]
        if setup_needed or not ts.setup_done:
            await self._setup(entry, ts)
        await run_lanes(self, entry, ts)

    async def _setup(self, entry: QueueEntry, ts: _TaskState) -> None:
        task, rt = entry.task, entry.runtime
        assert ts.devices is not None
        ts.setup_done = False
        ts.target = await self._steps.resolve_target(task)
        rt.resolved_ra, rt.resolved_dec = ts.target.ra, ts.target.dec
        has_coords = ts.target.ra is not None
        if task.slew and has_coords:
            await self._steps.stop_guiding(task.id)
            await self._steps.slew(task, ts.target, ts.devices.mount_id)
            ts.flipped = False
        if task.center:
            if has_coords:
                await center_with_retries(self, entry, ts)
            else:
                await self._steps.skipped(
                    task.id, "center", "the target has no coordinates (current pointing)"
                )
        if task.start_guiding:
            if getattr(self.app.state, "guider", None) is None:
                await self._steps.start_guiding(task.id)  # reported as skipped
            else:
                await ensure_guiding(self, entry, ts)
        if task.autofocus_at_start:
            for idx, lane in enumerate(task.lanes):
                ls = ts.lanes.setdefault(lane.id, _LaneState())
                await run_autofocus(self, entry, ls, ts.lane_devices[lane.id], "task start", idx)
        ts.frames_since_dither = 0
        for ls in ts.lanes.values():
            ls.current_filter = None
        ts.setup_done = True

    def pending_frame_request(self) -> _Request | None:
        """A request that takes effect at the next frame boundary (or now), if any."""
        req = self._request
        return req if req is not None and req.when in ("frame", "now") else None

    async def set_lane_activity(
        self, entry: QueueEntry, index: int, activity: Activity | None
    ) -> None:
        """Activity of a secondary lane (the primary's is set_activity)."""
        lanes = entry.runtime.lanes
        if 0 <= index < len(lanes) and lanes[index].activity != activity:
            lanes[index].activity = activity
            await self.emit_status()

    def exposure_started(self, duration: float | None) -> None:
        """The primary lane started (duration) or ended (None) an exposure."""
        self._exposure_started_at = _now() if duration is not None else None
        self._exposure_duration = duration

    def frame_saved(self) -> None:
        if self._run is not None:
            self._run.frames_saved += 1

    def _check_boundary(self) -> None:
        req = self._request
        if req is not None and req.when in ("frame", "now"):
            raise _BoundaryReached(req)

    async def _sleep(self, seconds: float, activity: Activity, message: str) -> None:
        """Sleep while honouring frame-boundary requests."""
        await self.set_activity(activity, message)
        deadline = time.monotonic() + seconds
        while True:
            self._check_boundary()
            left = deadline - time.monotonic()
            if left <= 0:
                return
            await asyncio.sleep(min(left, 1.0))

    # ── Meridian flip ──────────────────────────────────────────────────────

    async def _maybe_flip(self, entry: QueueEntry, ts: _TaskState, duration: float) -> None:
        """Flip now if due; if the next exposure would cross the flip point, wait for it."""
        cfg = self.settings
        mm = getattr(self.app.state, "mount_manager", None)
        mount_id = ts.devices.mount_id if ts.devices else None
        if not cfg.meridian_flip_enabled or mm is None or mount_id is None:
            return
        status = await self._mount_status(mount_id)
        if status is None or status.hour_angle is None:
            return
        ha = (status.hour_angle + 12.0) % 24.0 - 12.0
        threshold = cfg.meridian_flip_ha_hours
        known_pier = status.pier_side in ("East", "West")
        flip_coming = not (status.pier_side == "East" or (not known_pier and ts.flipped))
        if ts.schedule is not None:
            # Secondary lanes don't start frames that would still run at the flip point
            ts.schedule.flip_at = (
                time.monotonic() + max(0.0, threshold - ha) * 3600.0 / SIDEREAL_RATE
                if flip_coming
                else None
            )
            ts.schedule.notify()
        if not known_pier and ts.flipped:
            return  # unknown pier side: flip at most once per target
        if ha >= threshold:
            if meridian_flip_due(status.pier_side, ha) is not False:
                await self._flip(entry, ts, mount_id)
            return
        if status.pier_side == "East":
            return  # already on the side used for western targets: no flip coming
        ha_end = ha + (duration + FLIP_LOOKAHEAD_MARGIN_S) / 3600.0 * SIDEREAL_RATE
        if ha_end <= threshold:
            return
        wait_s = (threshold - ha) * 3600.0 / SIDEREAL_RATE
        await self.set_activity(
            Activity.WAITING, f"Waiting {math.ceil(wait_s / 60)} min for the meridian flip"
        )
        # Poll the mount rather than trusting a computed sleep: it's the mount's HA that
        # decides, and frame-boundary requests stay responsive meanwhile.
        while True:
            self._check_boundary()
            status = await self._mount_status(mount_id)
            if status is None or status.hour_angle is None:
                return
            ha = (status.hour_angle + 12.0) % 24.0 - 12.0
            if ha >= threshold:
                break
            left_s = (threshold - ha) * 3600.0 / SIDEREAL_RATE
            await asyncio.sleep(min(max(left_s, 0.05), FLIP_POLL_S))
        if meridian_flip_due(status.pier_side, ha) is not False:
            await self._flip(entry, ts, mount_id)

    async def _flip(self, entry: QueueEntry, ts: _TaskState, mount_id: str) -> None:
        await mount_operation(self, entry, ts, "meridian flip", self._flip_now(entry, ts, mount_id))

    async def _flip_now(self, entry: QueueEntry, ts: _TaskState, mount_id: str) -> None:
        task = entry.task
        await self._steps.stop_guiding(task.id)
        flipped = await self._steps.meridian_flip(task, mount_id)
        ts.flipped = True
        if ts.schedule is not None:
            ts.schedule.flip_at = None
        if (
            flipped
            and self.settings.center_after_flip
            and ts.target is not None
            and ts.target.ra is not None
        ):
            await center_with_retries(self, entry, ts)
        # Guiding restarts through ensure_guiding() before the next frame.
        ts.frames_since_dither = 0
        if flipped and self.settings.refocus_after_flip:
            for ls in ts.lanes.values():
                ls.af_due = "after the meridian flip"

    async def _mount_status(self, mount_id: str) -> Any:
        mm = getattr(self.app.state, "mount_manager", None)
        if mm is None:
            return None
        try:
            return await mm.get_status(mount_id)
        except Exception as exc:
            logger.warning("sequencer.mount_status_failed", mount_id=mount_id, error=str(exc))
            return None

    async def _pointing(self) -> tuple[float, float] | None:
        """Current mount RA/Dec in degrees (to detect a mount moved during a pause)."""
        mount_id = run_mount_id(self.app)
        if mount_id is None:
            return None
        status = await self._mount_status(mount_id)
        if status is None or status.ra is None or status.dec is None:
            return None
        return status.ra * 15.0, status.dec

    def _auto_flip_suspended(self, mount_id: str | None) -> contextlib.AbstractContextManager[None]:
        mm = getattr(self.app.state, "mount_manager", None)
        if mm is None or mount_id is None or not hasattr(mm, "suspend_auto_flip"):
            return contextlib.nullcontext()
        return cast(contextlib.AbstractContextManager[None], mm.suspend_auto_flip(mount_id))

    # ── Bookkeeping ────────────────────────────────────────────────────────

    async def _publish_interruption(
        self, task_id: str | None, req: _Request, record_on: QueueEntry | None = None
    ) -> Interruption:
        kind = "switch" if req.kind == "switch" else req.kind
        interruption = Interruption(at=_now(), kind=kind, actor=req.actor, reason=req.reason)
        await self.bus.publish(
            SequencerInterruption(
                task_id=task_id,
                kind=kind,
                actor=req.actor,
                reason=req.reason,
                boundary=req.when,
            )
        )
        logger.info(
            "sequencer.interruption", task_id=task_id, kind=kind, actor=req.actor, reason=req.reason
        )
        if record_on is not None:
            _record(record_on, interruption)
            await self._svc.commit()
        return interruption

    async def _finish_task(
        self, entry: QueueEntry, status: TaskStatus, interruption: Interruption | None = None
    ) -> None:
        rt = entry.runtime
        rt.status = status
        rt.stall = None
        for lr in rt.lanes:
            lr.activity = None
            lr.current_group = None
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED):
            rt.finished_at = _now()
        if interruption is not None:
            _record(entry, interruption)
        if self._current is entry:
            self._current = None
            self._activity = None
            self._message = None
        self._svc.task_left(entry.task.id)
        await self._svc.commit()
        await self.bus.publish(
            SequencerTaskFinished(task_id=entry.task.id, status=status, error=rt.last_error)
        )
        logger.info(
            "sequencer.task_finished", task_id=entry.task.id, status=status, error=rt.last_error
        )
        await self.emit_status()

    async def _interrupt_current(
        self, kind: Literal["cancel", "crash"], actor: Actor, reason: str
    ) -> None:
        entry = self._current
        if entry is None or entry.runtime.status != TaskStatus.RUNNING:
            return
        interruption = Interruption(at=_now(), kind=kind, actor=actor, reason=reason)
        with contextlib.suppress(Exception):
            await self._finish_task(entry, TaskStatus.INTERRUPTED, interruption)


# ── Helpers (pure) ─────────────────────────────────────────────────────────────


def _record(entry: QueueEntry, interruption: Interruption) -> None:
    items = entry.runtime.interruptions
    items.append(interruption)
    del items[:-MAX_INTERRUPTIONS]


def _separation_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    ra1, dec1 = map(math.radians, a)
    ra2, dec2 = map(math.radians, b)
    cos_sep = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(
        ra1 - ra2
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def lane_runtime(entry: QueueEntry, lane_id: str) -> LaneRuntime:
    return next(lr for lr in entry.runtime.lanes if lr.lane_id == lane_id)


def next_group(lane: Lane, lrt: LaneRuntime, ls: _LaneState, *, peek: bool = False) -> int | None:
    """Index of the group the lane's next frame belongs to, or None when the lane is done."""
    incomplete = [i for i, g in enumerate(lane.groups) if lrt.groups[i].frames_done < g.count]
    if not incomplete:
        return None
    if lane.order == "sequential":
        return incomplete[0]
    cur = ls.rr_group
    if cur is not None and cur in incomplete and ls.rr_taken < lane.round_robin_batch:
        return cur
    nxt = incomplete[0] if cur is None else next((i for i in incomplete if i > cur), incomplete[0])
    if not peek:
        ls.rr_group, ls.rr_taken = nxt, 0
    return nxt


def remaining_frames(entry: QueueEntry) -> int:
    lane = entry.task.lanes[0]
    lrt = lane_runtime(entry, lane.id)
    return sum(
        max(0, g.count - p.frames_done) for g, p in zip(lane.groups, lrt.groups, strict=True)
    )


def remaining_seconds(entry: QueueEntry) -> float:
    lane = entry.task.lanes[0]
    lrt = lane_runtime(entry, lane.id)
    return sum(
        max(0, g.count - p.frames_done) * g.duration
        for g, p in zip(lane.groups, lrt.groups, strict=True)
    )
