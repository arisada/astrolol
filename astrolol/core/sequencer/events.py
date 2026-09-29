"""Public sequencer events.

``sequencer.status`` and ``sequencer.queue_changed`` are full snapshots: a client never
has to rebuild state from deltas. The fine-grained events describe what happened; they
are also what the session journal records.
"""

from __future__ import annotations

from typing import Literal

from astrolol.core.events.models import BaseEvent
from astrolol.core.sequencer.models import (
    Actor,
    QueueEntry,
    RunOutcome,
    SequencerStatus,
    StallKind,
    TaskStatus,
)

StepKind = Literal[
    "unpark",
    "park",
    "resolve_target",
    "slew",
    "center",
    "stop_guiding",
    "start_guiding",
    "autofocus",
    "change_filter",
    "expose",
    "dither",
    "meridian_flip",
]

StepDetails = dict[str, str | float | int | bool | None]
"""Flat, journal-friendly step results (e.g. ``{"error_arcsec": 12.5, "attempts": 2}``)."""


class SequencerStatusChanged(BaseEvent):
    type: Literal["sequencer.status"] = "sequencer.status"
    status: SequencerStatus


class SequencerQueueChanged(BaseEvent):
    type: Literal["sequencer.queue_changed"] = "sequencer.queue_changed"
    entries: list[QueueEntry]


class SequencerSessionStarted(BaseEvent):
    type: Literal["sequencer.session_started"] = "sequencer.session_started"
    session_id: str
    actor: Actor


class SequencerSessionFinished(BaseEvent):
    type: Literal["sequencer.session_finished"] = "sequencer.session_finished"
    session_id: str
    outcome: RunOutcome
    error: str | None = None
    frames_saved: int = 0


class SequencerTaskStarted(BaseEvent):
    type: Literal["sequencer.task_started"] = "sequencer.task_started"
    task_id: str
    name: str
    resumed: bool = False


class SequencerTaskFinished(BaseEvent):
    type: Literal["sequencer.task_finished"] = "sequencer.task_finished"
    task_id: str
    status: TaskStatus
    error: str | None = None


class SequencerStepStarted(BaseEvent):
    type: Literal["sequencer.step_started"] = "sequencer.step_started"
    task_id: str | None = None
    lane_id: str | None = None
    step: StepKind
    message: str


class SequencerStepFinished(BaseEvent):
    type: Literal["sequencer.step_finished"] = "sequencer.step_finished"
    task_id: str | None = None
    lane_id: str | None = None
    step: StepKind
    duration_s: float
    details: StepDetails = {}


class SequencerStepSkipped(BaseEvent):
    type: Literal["sequencer.step_skipped"] = "sequencer.step_skipped"
    task_id: str | None = None
    lane_id: str | None = None
    step: StepKind
    reason: str


class SequencerStepFailed(BaseEvent):
    type: Literal["sequencer.step_failed"] = "sequencer.step_failed"
    task_id: str | None = None
    lane_id: str | None = None
    step: StepKind
    error: str
    handling: str  # what happened next: "continue", "skip", "defer", "pause", "abort", "retry"


class SequencerFrameSaved(BaseEvent):
    type: Literal["sequencer.frame_saved"] = "sequencer.frame_saved"
    task_id: str
    lane_id: str
    group_idx: int
    frame_idx: int  # 0-based index within the group
    frames_total: int
    filter_name: str | None
    duration: float
    fits_path: str
    counted: bool = True
    object_name: str | None = None
    # Conditions at the end of the exposure (None when unknown)
    altitude: float | None = None           # degrees
    hour_angle: float | None = None         # hours
    focuser_position: int | None = None
    sensor_temperature: float | None = None  # °C
    # Guiding during the exposure (None when there is no guider)
    guide_rms_total: float | None = None  # arcsec
    unguided_s: float | None = None  # seconds without active guiding
    guiding_losses: int | None = None  # times guiding was interrupted


class SequencerFrameDiscarded(BaseEvent):
    type: Literal["sequencer.frame_discarded"] = "sequencer.frame_discarded"
    task_id: str
    lane_id: str
    group_idx: int
    reason: str


class SequencerInterruption(BaseEvent):
    type: Literal["sequencer.interruption"] = "sequencer.interruption"
    task_id: str | None
    kind: Literal["pause", "stop", "switch", "defer", "skip", "cancel", "crash"]
    actor: Actor
    reason: str | None = None
    boundary: str | None = None
    stall_kind: StallKind | None = None


class SequencerResumed(BaseEvent):
    type: Literal["sequencer.resumed"] = "sequencer.resumed"
    task_id: str | None
    actor: Actor
    paused_s: float
    setup_rerun: bool


class SequencerTaskStalled(BaseEvent):
    type: Literal["sequencer.task_stalled"] = "sequencer.task_stalled"
    task_id: str
    kind: StallKind
    error: str


class SequencerStallAttempt(BaseEvent):
    type: Literal["sequencer.stall_attempt"] = "sequencer.stall_attempt"
    task_id: str
    kind: StallKind
    attempt: int
    error: str | None = None


class SequencerTaskUnstalled(BaseEvent):
    type: Literal["sequencer.task_unstalled"] = "sequencer.task_unstalled"
    task_id: str
    kind: StallKind
    duration_s: float
    attempts: int
