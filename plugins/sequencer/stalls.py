"""Stall bookkeeping: a sky-dependent step that keeps failing and is being retried.

A stall is visible (``TaskRuntime.stall`` / ``SequencerStatus.stall``), announced
(``task_stalled`` once, ``stall_attempt`` per retry, ``task_unstalled`` on recovery) and
bounded only by ``stall_timeout_min`` (None = retry until someone decides otherwise).
Retrying, waiting and boundary checks are the caller's job.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from astrolol.core.sequencer.events import (
    SequencerStallAttempt,
    SequencerTaskStalled,
    SequencerTaskUnstalled,
    StepKind,
)
from astrolol.core.sequencer.models import QueueEntry, Stall, StallKind
from plugins.sequencer.steps import StepError

if TYPE_CHECKING:
    from plugins.sequencer.runner import Runner

logger = structlog.get_logger()

_STEP: dict[StallKind, StepKind] = {
    StallKind.GUIDING: "start_guiding",
    StallKind.CENTERING: "center",
    StallKind.AUTOFOCUS: "autofocus",
}


class StallTracker:
    def __init__(self, runner: Runner, entry: QueueEntry, kind: StallKind) -> None:
        self._runner = runner
        self._entry = entry
        self.kind = kind
        self._started: float | None = None  # monotonic

    @property
    def stalled(self) -> bool:
        return self._started is not None

    async def begin(self, error: str) -> None:
        """Enter the stall (idempotent)."""
        if self._started is not None:
            return
        self._started = time.monotonic()
        rt = self._entry.runtime
        rt.stall = Stall(kind=self.kind, since=datetime.now(UTC), attempts=0, last_error=error)
        await self._runner.bus.publish(
            SequencerTaskStalled(
                task_id=self._entry.task.id,
                kind=self.kind,
                error=error,
                notify="warning",
                notify_title="Task stalled",
                notify_body=f"{self._entry.task.id}: {self.kind.value} keeps failing — {error}",
            )
        )
        logger.warning(
            "sequencer.task_stalled", task_id=self._entry.task.id, kind=self.kind, error=error
        )
        await self._runner.commit()

    async def attempt(self, error: str | None, next_in_s: float | None) -> None:
        """Record a retry. A failed one (error set) also starts the stall if needed."""
        if error is not None:
            await self.begin(error)
        stall = self._entry.runtime.stall
        if stall is None:
            return
        stall.attempts += 1
        stall.last_error = error or stall.last_error
        stall.next_attempt_at = (
            datetime.now(UTC) + timedelta(seconds=next_in_s)
            if error is not None and next_in_s
            else None
        )
        await self._runner.bus.publish(
            SequencerStallAttempt(
                task_id=self._entry.task.id,
                kind=self.kind,
                attempt=stall.attempts,
                error=error,
            )
        )
        logger.info(
            "sequencer.stall_attempt",
            task_id=self._entry.task.id,
            kind=self.kind,
            attempt=stall.attempts,
            error=error,
        )
        await self._runner.commit()

    def check_timeout(self) -> None:
        """Raise the stall as a StepError once it has lasted longer than stall_timeout_min."""
        limit = self._runner.settings.stall_timeout_min
        if self._started is None or limit is None:
            return
        lasted = time.monotonic() - self._started
        if lasted >= limit * 60:
            stall = self._entry.runtime.stall
            last = stall.last_error if stall else None
            raise StepError(
                _STEP[self.kind],
                f"{self.kind.value} stalled for {lasted / 60:.0f} min"
                + (f": {last}" if last else ""),
                stall_kind=self.kind,
            )

    async def recovered(self) -> None:
        if self._started is None:
            return
        duration = time.monotonic() - self._started
        stall = self._entry.runtime.stall
        attempts = stall.attempts if stall else 0
        self._started = None
        self._entry.runtime.stall = None
        await self._runner.bus.publish(
            SequencerTaskUnstalled(
                task_id=self._entry.task.id,
                kind=self.kind,
                duration_s=round(duration, 1),
                attempts=attempts,
                notify="info",
                notify_title="Task recovered",
                notify_body=f"{self._entry.task.id}: {self.kind.value} recovered after {duration / 60:.0f} min",
            )
        )
        logger.info(
            "sequencer.task_unstalled",
            task_id=self._entry.task.id,
            kind=self.kind,
            duration_s=round(duration, 1),
            attempts=attempts,
        )
        await self._runner.commit()
