"""Sequencer-specific event models."""
from __future__ import annotations

from typing import Literal

from astrolol.core.events.models import BaseEvent


class SequenceStarted(BaseEvent):
    type: Literal["sequencer.started"] = "sequencer.started"
    task_count: int


class SequenceStepChanged(BaseEvent):
    type: Literal["sequencer.step_changed"] = "sequencer.step_changed"
    state: str
    message: str


class SequenceFrameCompleted(BaseEvent):
    type: Literal["sequencer.frame_completed"] = "sequencer.frame_completed"
    task_id: str
    group_idx: int
    frame_idx: int        # 0-based, within the group
    frames_total: int
    fits_path: str


class SequenceTaskCompleted(BaseEvent):
    type: Literal["sequencer.task_completed"] = "sequencer.task_completed"
    task_id: str


class SequenceTaskFailed(BaseEvent):
    type: Literal["sequencer.task_failed"] = "sequencer.task_failed"
    task_id: str
    reason: str


class SequencePaused(BaseEvent):
    type: Literal["sequencer.paused"] = "sequencer.paused"


class SequenceResumed(BaseEvent):
    type: Literal["sequencer.resumed"] = "sequencer.resumed"


class SequenceCompleted(BaseEvent):
    type: Literal["sequencer.completed"] = "sequencer.completed"
    tasks_done: int


class SequenceFailed(BaseEvent):
    type: Literal["sequencer.failed"] = "sequencer.failed"
    reason: str


class SequenceCancelled(BaseEvent):
    type: Literal["sequencer.cancelled"] = "sequencer.cancelled"
