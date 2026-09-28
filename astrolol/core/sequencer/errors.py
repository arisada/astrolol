"""Typed errors raised by ``Sequencer`` implementations (mapped to HTTP codes by REST)."""

from __future__ import annotations

from astrolol.core.sequencer.models import PreflightReport


class SequencerError(Exception):
    """Base class for sequencer errors."""


class SequencerBusy(SequencerError):
    """A run is already in progress (or the operation needs an idle sequencer)."""


class SequencerNotRunning(SequencerError):
    """The operation needs an active run."""


class TaskNotFound(SequencerError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"Task '{task_id}' not found")
        self.task_id = task_id


class TaskLocked(SequencerError):
    """The task is running and can't be modified or removed."""


class InvalidRequest(SequencerError):
    """The request is not valid in the current state (e.g. switching to a completed task)."""


class PreflightFailed(SequencerError):
    def __init__(self, report: PreflightReport) -> None:
        errors = [i.message for i in report.issues if i.severity == "error"]
        super().__init__("Pre-flight check failed: " + "; ".join(errors))
        self.report = report
