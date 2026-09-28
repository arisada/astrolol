"""The ``Sequencer`` protocol — the interface, with no logic.

A sequencer plugin registers an implementation as ``app.state.sequencer``. Consumers
(REST routers, schedulers, scripts, MCP) depend only on this protocol and the models in
``astrolol.core.sequencer``, never on a plugin, so implementations are interchangeable.

All methods raise the errors from ``astrolol.core.sequencer.errors``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, runtime_checkable

from astrolol.core.events.models import BaseEvent
from astrolol.core.sequencer.models import (
    Actor,
    Boundary,
    ImagingTask,
    PreflightReport,
    QueueEntry,
    RunOutcome,
    SequencerStatus,
    TaskRuntime,
)


@runtime_checkable
class Sequencer(Protocol):
    # ── Queue ─────────────────────────────────────────────────────────────
    async def list_tasks(self) -> list[QueueEntry]:
        """The whole queue, in execution order."""
        ...

    async def get(self, task_id: str) -> QueueEntry: ...

    async def add(self, task: ImagingTask, *, position: int | None = None) -> QueueEntry:
        """Append (or insert at *position*) a task. Task and lane ids are server-assigned."""
        ...

    async def insert_next(self, task: ImagingTask) -> QueueEntry:
        """Insert a task right after the current (or next runnable) task."""
        ...

    async def update(self, task_id: str, task: ImagingTask) -> QueueEntry:
        """Replace a task's definition, keeping its progress where lanes/groups still match.

        Raises TaskLocked if the task is running.
        """
        ...

    async def remove(self, task_id: str) -> None: ...

    async def reorder(self, order: list[str]) -> None:
        """Reorder the queue; ids not listed keep their relative order after the listed ones."""
        ...

    async def duplicate(self, task_id: str) -> QueueEntry:
        """Insert a fresh copy (new ids, no progress) right after the original."""
        ...

    async def reset_progress(self, task_id: str) -> QueueEntry: ...

    async def set_status(
        self, task_id: str, status: Literal["pending", "skipped"], *, actor: Actor = "api"
    ) -> QueueEntry:
        """Mark a task skipped, or back to pending (retry a failed/skipped task; progress kept)."""
        ...

    async def clear(self, statuses: list[str]) -> None:
        """Remove every non-running task whose status is in *statuses*."""
        ...

    # ── Control ───────────────────────────────────────────────────────────
    async def preflight(self, task_ids: list[str] | None = None) -> PreflightReport: ...

    async def start(
        self,
        *,
        from_task: str | None = None,
        only: list[str] | None = None,
        actor: Actor = "api",
    ) -> None:
        """Start a run over the runnable (pending or interrupted) tasks.

        Raises SequencerBusy if running, PreflightFailed if pre-flight has errors.
        """
        ...

    async def pause(self, when: Boundary = "frame", *, actor: Actor = "api") -> None: ...

    async def resume(self, *, actor: Actor = "api") -> None: ...

    async def stop(
        self, when: Boundary = "frame", *, actor: Actor = "api", reason: str | None = None
    ) -> None:
        """Graceful stop: the current task becomes interrupted (progress kept)."""
        ...

    async def skip_current(self, when: Boundary = "frame", *, actor: Actor = "api") -> None: ...

    async def cancel(self, *, actor: Actor = "api") -> None:
        """Same as stop("now")."""
        ...

    async def switch_to(
        self,
        task_id: str,
        when: Boundary = "frame",
        *,
        actor: Actor = "api",
        reason: str | None = None,
    ) -> None:
        """Interrupt the current task at *when* and continue the same run with *task_id*.

        No park, unpark or session change. If idle, equivalent to start(only=[task_id]).
        """
        ...

    # ── Observation ───────────────────────────────────────────────────────
    def status(self) -> SequencerStatus: ...

    async def wait_for_task(self, task_id: str) -> TaskRuntime:
        """Resolve when the task leaves RUNNING (completed, interrupted, failed, skipped)."""
        ...

    async def wait_idle(self) -> RunOutcome | None:
        """Resolve when no run is active; returns the last run's outcome."""
        ...

    def subscribe(self) -> AsyncIterator[BaseEvent]:
        """Async iterator over sequencer events (``sequencer.*``) from now on."""
        ...
