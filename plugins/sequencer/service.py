"""SequencerServiceImpl — this plugin's implementation of the core ``Sequencer`` protocol.

Owns the queue (definitions + runtime, persisted by QueueStore) and delegates execution
to the Runner. Registered as ``app.state.sequencer``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from astrolol.core.events.models import BaseEvent
from astrolol.core.sequencer.errors import InvalidRequest, TaskLocked, TaskNotFound
from astrolol.core.sequencer.events import SequencerQueueChanged
from astrolol.core.sequencer.models import (
    Actor,
    Boundary,
    ExposureGroup,
    GroupProgress,
    ImagingTask,
    Interruption,
    LaneRuntime,
    PreflightIssue,
    PreflightReport,
    QueueEntry,
    RunOutcome,
    SequencerStatus,
    TaskRuntime,
    TaskStatus,
)
from plugins.sequencer.devices import resolve_lane_devices
from plugins.sequencer.runner import RUNNABLE, SWITCHABLE, Runner, remaining_frames
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.store import QueueStore

logger = structlog.get_logger()


def _uid() -> str:
    return str(uuid.uuid4())


def _fresh_runtime(task: ImagingTask) -> TaskRuntime:
    return TaskRuntime(
        task_id=task.id,
        lanes=[
            LaneRuntime(lane_id=lane.id, groups=[GroupProgress() for _ in lane.groups])
            for lane in task.lanes
        ],
    )


def _with_new_ids(task: ImagingTask) -> ImagingTask:
    return task.model_copy(
        update={
            "id": _uid(),
            "lanes": [lane.model_copy(update={"id": _uid()}) for lane in task.lanes],
        }
    )


def _same_group(a: ExposureGroup, b: ExposureGroup) -> bool:
    """Frames taken for *a* still count for *b* (only the count may differ)."""
    return (a.filter_name, a.duration, a.binning, a.gain, a.frame_type) == (
        b.filter_name,
        b.duration,
        b.binning,
        b.gain,
        b.frame_type,
    )


class SequencerServiceImpl:
    def __init__(self, app: Any, bus: Any, settings: SequencerSettings, store: QueueStore) -> None:
        self.app = app
        self.bus = bus
        self._settings = settings
        self._store = store
        self._entries: list[QueueEntry] = store.load()
        self._changed = asyncio.Event()
        self._left: dict[str, int] = {}  # task_id → times it left RUNNING (for wait_for_task)
        self.runner = Runner(self)

    # ── Internal API used by the runner ────────────────────────────────────

    @property
    def settings(self) -> SequencerSettings:
        return self._settings

    def update_settings(self, settings: SequencerSettings) -> None:
        self._settings = settings

    @property
    def entries(self) -> list[QueueEntry]:
        return self._entries

    def find(self, task_id: str) -> QueueEntry | None:
        return next((e for e in self._entries if e.task.id == task_id), None)

    def _entry(self, task_id: str) -> QueueEntry:
        entry = self.find(task_id)
        if entry is None:
            raise TaskNotFound(task_id)
        return entry

    def _index(self, task_id: str) -> int:
        return next(i for i, e in enumerate(self._entries) if e.task.id == task_id)

    async def commit(self) -> None:
        """Persist the queue and announce it."""
        self._store.save(self._entries)
        await self.bus.publish(
            SequencerQueueChanged(entries=[e.model_copy(deep=True) for e in self._entries])
        )
        # Queue edits change status counters (tasks_total, eta) too.
        await self.runner.emit_status()

    def notify(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    def task_left(self, task_id: str) -> None:
        self._left[task_id] = self._left.get(task_id, 0) + 1

    def _check_not_running(self, entry: QueueEntry) -> None:
        if entry.runtime.status == TaskStatus.RUNNING:
            raise TaskLocked(f"Task '{entry.task.display_name}' is running")

    # ── Queue ──────────────────────────────────────────────────────────────

    async def list_tasks(self) -> list[QueueEntry]:
        return [e.model_copy(deep=True) for e in self._entries]

    async def get(self, task_id: str) -> QueueEntry:
        return self._entry(task_id).model_copy(deep=True)

    async def add(self, task: ImagingTask, *, position: int | None = None) -> QueueEntry:
        task = _with_new_ids(task)
        entry = QueueEntry(task=task, runtime=_fresh_runtime(task))
        if position is None or position >= len(self._entries):
            self._entries.append(entry)
        else:
            self._entries.insert(max(0, position), entry)
        await self.commit()
        logger.info("sequencer.task_added", task_id=task.id, name=task.display_name)
        return entry.model_copy(deep=True)

    async def insert_next(self, task: ImagingTask) -> QueueEntry:
        current = self.runner.current_task_id
        if current is not None:
            position = self._index(current) + 1
        else:
            position = next(
                (i for i, e in enumerate(self._entries) if e.runtime.status in RUNNABLE),
                len(self._entries),
            )
        return await self.add(task, position=position)

    async def update(self, task_id: str, task: ImagingTask) -> QueueEntry:
        entry = self._entry(task_id)
        self._check_not_running(entry)
        old_lanes = {
            lane.id: (lane, lr)
            for lane, lr in zip(entry.task.lanes, entry.runtime.lanes, strict=True)
        }
        new_lanes, new_lrs, seen = [], [], set()
        for lane in task.lanes:
            if lane.id in old_lanes and lane.id not in seen:
                old_lane, old_lr = old_lanes[lane.id]
                groups = [
                    GroupProgress(frames_done=old_lr.groups[i].frames_done)
                    if i < len(old_lane.groups) and _same_group(old_lane.groups[i], g)
                    else GroupProgress()
                    for i, g in enumerate(lane.groups)
                ]
            else:
                lane = lane.model_copy(update={"id": _uid()})
                groups = [GroupProgress() for _ in lane.groups]
            seen.add(lane.id)
            new_lanes.append(lane)
            new_lrs.append(LaneRuntime(lane_id=lane.id, groups=groups))
        entry.task = task.model_copy(update={"id": task_id, "lanes": new_lanes})
        entry.runtime = entry.runtime.model_copy(update={"lanes": new_lrs})
        if entry.runtime.status == TaskStatus.COMPLETED and remaining_frames(entry) > 0:
            entry.runtime.status = (
                TaskStatus.INTERRUPTED if entry.runtime.frames_done() > 0 else TaskStatus.PENDING
            )
        await self.commit()
        logger.info("sequencer.task_updated", task_id=task_id)
        return entry.model_copy(deep=True)

    async def remove(self, task_id: str) -> None:
        entry = self._entry(task_id)
        self._check_not_running(entry)
        self._entries.remove(entry)
        await self.commit()
        logger.info("sequencer.task_removed", task_id=task_id)

    async def reorder(self, order: list[str]) -> None:
        rank = {tid: i for i, tid in enumerate(order)}
        listed = sorted(
            (e for e in self._entries if e.task.id in rank), key=lambda e: rank[e.task.id]
        )
        rest = [e for e in self._entries if e.task.id not in rank]
        self._entries[:] = listed + rest
        await self.commit()

    async def duplicate(self, task_id: str) -> QueueEntry:
        entry = self._entry(task_id)
        copy = entry.task.model_copy(deep=True)
        return await self.add(copy, position=self._index(task_id) + 1)

    async def reset_progress(self, task_id: str) -> QueueEntry:
        entry = self._entry(task_id)
        self._check_not_running(entry)
        entry.runtime = _fresh_runtime(entry.task)
        await self.commit()
        return entry.model_copy(deep=True)

    async def set_status(
        self, task_id: str, status: Literal["pending", "skipped"], *, actor: Actor = "api"
    ) -> QueueEntry:
        entry = self._entry(task_id)
        if entry.runtime.status == TaskStatus.RUNNING:
            raise InvalidRequest("The task is running; use skip_current to skip it")
        rt = entry.runtime
        if status == "skipped":
            rt.status = TaskStatus.SKIPPED
            rt.interruptions.append(Interruption(at=datetime.now(UTC), kind="skip", actor=actor))
        else:
            # Make the task runnable again, keeping its progress (retry).
            rt.status = TaskStatus.INTERRUPTED if rt.frames_done() > 0 else TaskStatus.PENDING
            rt.last_error = None
            if remaining_frames(entry) == 0:
                rt.status = TaskStatus.COMPLETED
        await self.commit()
        return entry.model_copy(deep=True)

    async def clear(self, statuses: list[str]) -> None:
        wanted = {TaskStatus(s) for s in statuses} - {TaskStatus.RUNNING}
        self._entries[:] = [e for e in self._entries if e.runtime.status not in wanted]
        await self.commit()

    # ── Pre-flight ─────────────────────────────────────────────────────────

    async def preflight(self, task_ids: list[str] | None = None) -> PreflightReport:
        if task_ids is None:
            entries = [e for e in self._entries if e.runtime.status in RUNNABLE]
        else:
            entries = [self._entry(t) for t in task_ids]
        issues: list[PreflightIssue] = []
        if not entries:
            issues.append(
                PreflightIssue(severity="error", code="nothing_to_run", message="No task to run")
            )
        for entry in entries:
            issues.extend(await self._preflight_task(entry))
        return PreflightReport(ok=not any(i.severity == "error" for i in issues), issues=issues)

    async def _preflight_task(self, entry: QueueEntry) -> list[PreflightIssue]:
        task = entry.task
        state = self.app.state
        issues: list[PreflightIssue] = []

        def issue(
            severity: Literal["error", "warning"],
            code: str,
            message: str,
            lane_id: str | None = None,
        ) -> None:
            issues.append(
                PreflightIssue(
                    severity=severity,
                    task_id=task.id,
                    lane_id=lane_id,
                    code=code,
                    message=f"{task.display_name}: {message}",
                )
            )

        if len(task.lanes) > 1:
            issue(
                "error", "multi_lane_unsupported", "several cameras per task are not supported yet"
            )
        cameras: set[str] = set()
        mount_id: str | None = None
        for lane in task.lanes:
            devices = resolve_lane_devices(self.app, lane)
            if devices.camera_id is None:
                issue(
                    "error",
                    "camera_not_connected",
                    f"camera '{lane.camera_id or 'main camera'}' is not connected",
                    lane.id,
                )
                continue
            if devices.camera_id in cameras:
                issue(
                    "error",
                    "camera_reused",
                    f"camera '{devices.camera_id}' is used by two lanes",
                    lane.id,
                )
            cameras.add(devices.camera_id)
            mount_id = mount_id or devices.mount_id
            wanted = {g.filter_name for g in lane.groups if g.filter_name is not None}
            if wanted:
                await self._preflight_filters(
                    devices.filter_wheel_id, devices.camera_id, wanted, issue, lane.id
                )

        target = task.target
        if target.kind != "current" and (task.slew or task.center):
            if task.slew and mount_id is None:
                issue("error", "no_mount", "slewing needs a connected mount")
            has_snapshot = target.ra is not None
            if target.kind == "favorite" and not has_snapshot:
                favorites = getattr(state, "target_favorites", None)
                if favorites is None or favorites.get(target.favorite_id) is None:
                    issue(
                        "error", "target_unresolvable", f"favorite '{target.name}' can't be found"
                    )
            if (
                target.kind == "catalog"
                and not has_snapshot
                and getattr(state, "object_resolver", None) is None
            ):
                issue(
                    "error",
                    "target_unresolvable",
                    f"'{target.name}' can't be resolved: the object resolver plugin is not enabled",
                )

        if task.center and target.kind != "current":
            solve_manager = getattr(state, "solve_manager", None)
            if solve_manager is None or not hasattr(solve_manager, "center"):
                issue(
                    "warning",
                    "no_centering",
                    "centering is unavailable (plate solving plugin); slew only",
                )
        phd2 = getattr(state, "phd2_client", None)
        if task.start_guiding or task.dither_every:
            if phd2 is None:
                issue(
                    "warning",
                    "no_guider",
                    "the PHD2 plugin is not enabled: no guiding or dithering",
                )
            elif not phd2.get_status().connected:
                issue("warning", "guider_disconnected", "PHD2 is not connected")
        if task.autofocus_at_start or any(lane.autofocus_on_filter_change for lane in task.lanes):
            issue("warning", "no_autofocus", "autofocus integration is not implemented yet")
        return issues

    async def _preflight_filters(
        self, fw_id: str | None, camera_id: str, wanted: set[str], issue: Any, lane_id: str
    ) -> None:
        fwm = getattr(self.app.state, "filter_wheel_manager", None)
        if fw_id is None or fwm is None:
            issue(
                "error",
                "no_filter_wheel",
                f"filters are requested but camera '{camera_id}' has no filter wheel",
                lane_id,
            )
            return
        try:
            status = await fwm.get_status(fw_id)
        except Exception as exc:
            issue(
                "warning",
                "filter_wheel_unreadable",
                f"could not read filter wheel '{fw_id}': {exc}",
                lane_id,
            )
            return
        missing = sorted(wanted - set(status.filter_names or []))
        if missing:
            issue(
                "error",
                "filter_not_in_wheel",
                f"filter(s) {', '.join(missing)} not in wheel '{fw_id}' "
                f"({', '.join(status.filter_names or []) or 'no names'})",
                lane_id,
            )

    # ── Control ────────────────────────────────────────────────────────────

    async def start(
        self,
        *,
        from_task: str | None = None,
        only: list[str] | None = None,
        actor: Actor = "api",
    ) -> None:
        only_set = set(only) if only is not None else None
        for tid in only or []:
            self._entry(tid)
        candidates = [
            e
            for e in self._entries
            if e.runtime.status in RUNNABLE and (only_set is None or e.task.id in only_set)
        ]
        excluded: set[str] = set()
        if from_task is not None:
            self._entry(from_task)
            ids = [e.task.id for e in candidates]
            if from_task not in ids:
                raise InvalidRequest("The task to start from is not pending or interrupted")
            excluded = set(ids[: ids.index(from_task)])
            candidates = [e for e in candidates if e.task.id not in excluded]
        await self.runner.start(candidates, excluded, only_set, actor)

    async def pause(self, when: Boundary = "frame", *, actor: Actor = "api") -> None:
        await self.runner.request("pause", when, actor)

    async def resume(self, *, actor: Actor = "api") -> None:
        await self.runner.resume(actor)

    async def stop(
        self, when: Boundary = "frame", *, actor: Actor = "api", reason: str | None = None
    ) -> None:
        await self.runner.request("stop", when, actor, reason)

    async def skip_current(self, when: Boundary = "frame", *, actor: Actor = "api") -> None:
        await self.runner.request("skip", when, actor)

    async def cancel(self, *, actor: Actor = "api") -> None:
        await self.runner.request("cancel", "now", actor)

    async def switch_to(
        self,
        task_id: str,
        when: Boundary = "frame",
        *,
        actor: Actor = "api",
        reason: str | None = None,
    ) -> None:
        entry = self._entry(task_id)
        if self.runner.current_task_id == task_id:
            return
        if entry.runtime.status not in SWITCHABLE:
            raise InvalidRequest(f"Can't switch to a {entry.runtime.status.value} task")
        if not self.runner.is_running:
            if entry.runtime.status not in RUNNABLE:
                await self.set_status(task_id, "pending", actor=actor)
            await self.start(only=[task_id], actor=actor)
            return
        await self.runner.request("switch", when, actor, reason, task_id=task_id)

    # ── Observation ────────────────────────────────────────────────────────

    def status(self) -> SequencerStatus:
        return self.runner.status()

    async def wait_for_task(self, task_id: str) -> TaskRuntime:
        entry = self._entry(task_id)
        if entry.runtime.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED):
            return entry.runtime.model_copy(deep=True)
        start = self._left.get(task_id, 0)
        while self._left.get(task_id, 0) == start:
            await self._changed.wait()
            if self.find(task_id) is None:
                raise TaskNotFound(task_id)
        return self._entry(task_id).runtime.model_copy(deep=True)

    async def wait_idle(self) -> RunOutcome | None:
        return await self.runner.wait_idle()

    async def subscribe(self) -> AsyncIterator[BaseEvent]:
        q = self.bus.subscribe()
        try:
            while True:
                event = await q.get()
                if getattr(event, "type", "").startswith("sequencer."):
                    yield event
        finally:
            self.bus.unsubscribe(q)
