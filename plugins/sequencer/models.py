"""Sequencer data models."""
from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class FilterExposure(BaseModel):
    filter_name: str | None = None   # None = don't touch the filter wheel
    duration: float                  # seconds
    count: int                       # total frames to take (not remaining)
    binning: int = 1
    gain: int = 0
    refocus: bool = False            # STUB: trigger autofocus before this group


class ImagingTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str | None = None

    # Target (all optional — omit to keep current pointing)
    target_name: str | None = None
    target_ra: float | None = None    # degrees J2000
    target_dec: float | None = None   # degrees J2000

    # Device selection (None = first connected device of that kind)
    camera_device_id: str | None = None
    filter_wheel_device_id: str | None = None

    # Ordered exposure plan
    exposures: list[FilterExposure]   # executed in order

    # Per-task setup (run once before first frame)
    do_slew: bool = True              # slew to target before starting
    do_plate_solve: bool = True       # plate solve + sync after slew

    # Per-task imaging behaviour
    dither_every: int | None = 1      # dither every N subs; None = never
    sub_delay_s: float = 0.0          # seconds to wait between subs

    # Error policy
    on_error: Literal["skip", "pause", "abort"] = "pause"
    # skip   = log the error, mark task failed, move to next task
    # pause  = halt queue and surface the error; user must resume manually
    # abort  = cancel entire queue


class TaskStatus(StrEnum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


class SequencerState(StrEnum):
    IDLE           = "idle"
    UNPARKING      = "unparking"
    SLEWING        = "slewing"
    PLATE_SOLVING  = "plate_solving"
    FOCUSING       = "focusing"      # reserved — autofocus stub
    GUIDING        = "guiding"       # starting / waiting for settle
    IMAGING        = "imaging"
    DITHERING      = "dithering"
    MERIDIAN_FLIP  = "meridian_flip"
    PAUSED         = "paused"
    PARKING        = "parking"
    COMPLETED      = "completed"
    FAILED         = "failed"
    CANCELLED      = "cancelled"


class SequencerStatus(BaseModel):
    state: SequencerState
    current_task_id: str | None = None
    current_task_name: str | None = None
    current_group_idx: int | None = None
    frames_done: int | None = None      # frames done in current group
    frames_total: int | None = None     # total frames in current group
    step_message: str | None = None     # human-readable current action
    error: str | None = None            # last error if state == failed/paused
    queue_length: int = 0               # total tasks in queue
    tasks_done: int = 0                 # completed tasks so far
