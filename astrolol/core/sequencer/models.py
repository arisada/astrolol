"""Public data contract of the sequencer.

These models are part of the ``Sequencer`` protocol's signatures, so they live in core:
any sequencer implementation, and any consumer (scheduler, scripts, MCP, REST), shares
them. Implementation details (settings, storage format, runner state) do not belong here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _uid() -> str:
    return str(uuid.uuid4())


Boundary = Literal["now", "frame", "task"]
"""Where a control request takes effect.

- ``now``   — abort in-flight exposures (frames discarded) and act immediately
- ``frame`` — let in-flight exposures finish, act before the next one starts
- ``task``  — let the current task finish, act before the next task starts
"""

Actor = str
"""Who issued a control request: ``"user"``, ``"scheduler:<id>"``, ``"script:<name>"``,
``"api"`` or ``"system"``. Recorded with every interruption."""


# ── Task definition ───────────────────────────────────────────────────────────


class TargetRef(BaseModel):
    """A reference to a target, resolved to coordinates when the task starts.

    Solar-system objects move and favorites can be edited, so the reference is kept and
    resolved at execution time. ``ra``/``dec`` hold a snapshot taken when the target was
    picked; they are the fallback if the source is gone and the value for
    ``kind="coordinates"``.
    """

    kind: Literal["favorite", "catalog", "coordinates", "current"] = Field(
        description=(
            "favorite: a target-plugin favorite; catalog: an object_resolver name; "
            "coordinates: fixed ICRS coordinates; current: don't slew, image where the "
            "mount points"
        )
    )
    name: str = Field(description="Display name; also used for the FITS OBJECT header and %O")
    favorite_id: str | None = Field(default=None, description="kind=favorite: the favorite's id")
    catalog_id: str | None = Field(
        default=None, description="kind=catalog: name to resolve, e.g. 'M 31' or 'Jupiter'"
    )
    ra: float | None = Field(
        default=None, ge=0.0, lt=360.0, description="Snapshot ICRS RA, degrees"
    )
    dec: float | None = Field(
        default=None, ge=-90.0, le=90.0, description="Snapshot ICRS Dec, degrees"
    )

    @model_validator(mode="after")
    def _check_kind_fields(self) -> TargetRef:
        if self.kind == "favorite" and not self.favorite_id:
            raise ValueError("kind='favorite' requires favorite_id")
        if self.kind == "catalog" and not self.catalog_id:
            raise ValueError("kind='catalog' requires catalog_id")
        if self.kind == "coordinates" and (self.ra is None or self.dec is None):
            raise ValueError("kind='coordinates' requires ra and dec")
        if (self.ra is None) != (self.dec is None):
            raise ValueError("ra and dec must be given together")
        return self


class ExposureGroup(BaseModel):
    """A block of identical frames within a lane."""

    filter_name: str | None = Field(
        default=None, description="Filter wheel slot name; null = don't touch the wheel"
    )
    duration: float = Field(gt=0, description="Exposure duration, seconds")
    count: int = Field(ge=1, description="Total frames wanted")
    binning: int = Field(default=1, ge=1, le=4)
    gain: int | None = Field(default=None, ge=0, description="null = leave driver gain unchanged")
    frame_type: Literal["light", "dark", "flat", "bias"] = "light"


class Lane(BaseModel):
    """One camera's exposure plan within a task. ``task.lanes[0]`` is the primary."""

    id: str = Field(default_factory=_uid, description="Server-assigned, stable")
    camera_id: str | None = Field(
        default=None, description="Camera device id; null = the profile's main camera"
    )
    groups: list[ExposureGroup] = Field(min_length=1)
    order: Literal["sequential", "round_robin"] = Field(
        default="sequential",
        description="sequential: all of group 0, then group 1…; round_robin: batches in turn",
    )
    round_robin_batch: int = Field(default=1, ge=1, description="Frames per group per round")
    autofocus_on_filter_change: bool = False
    target_temperature: float | None = Field(
        default=None,
        ge=-60.0,
        le=40.0,
        description="Sensor set point, °C, applied when the task starts; null = leave the cooler alone",
    )


class ImagingTask(BaseModel):
    """The definition of one queue item: a target, and what to shoot on it."""

    id: str = Field(default_factory=_uid, description="Server-assigned once, stable forever")
    name: str | None = Field(default=None, description="Defaults to target.name")
    target: TargetRef
    lanes: list[Lane] = Field(min_length=1, description="lanes[0] is the primary lane")

    slew: bool = Field(default=True, description="Slew to the target (ignored for kind=current)")
    center: bool = Field(default=True, description="Plate-solve centering after the slew")
    start_guiding: bool = Field(default=True, description="Start guiding and wait for settle")
    autofocus_at_start: bool = False
    wait_for_temperature: bool = Field(
        default=False,
        description="Before imaging, wait until every cooled camera with a set point reaches it",
    )

    dither_every: int | None = Field(
        default=1, ge=1, description="Dither every N primary-lane frames; null = never"
    )
    sub_delay_s: float = Field(default=0.0, ge=0, description="Pause between primary frames")
    on_error: Literal["skip", "defer", "pause", "abort"] = Field(
        default="pause",
        description=(
            "skip: task failed, next task; defer: task interrupted (resumable), next task; "
            "pause: pause the run, resume retries; abort: end the run"
        ),
    )

    @property
    def display_name(self) -> str:
        return self.name or self.target.name


# ── Runtime ───────────────────────────────────────────────────────────────────


class TaskStatus(StrEnum):
    PENDING = "pending"  # never started, or progress reset
    RUNNING = "running"
    INTERRUPTED = "interrupted"  # task-level pause: stopped, switched away, deferred; resumable
    COMPLETED = "completed"
    FAILED = "failed"  # error under on_error=skip/abort; progress kept; retryable
    SKIPPED = "skipped"


class RunState(StrEnum):
    """The runner's lifecycle — the only thing UI controls should depend on."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSING = "pausing"  # pause requested, waiting for the boundary
    PAUSED = "paused"
    STOPPING = "stopping"  # stop requested, waiting for the boundary


class Activity(StrEnum):
    """What the hardware is doing right now."""

    UNPARKING = "unparking"
    SLEWING = "slewing"
    CENTERING = "centering"
    STARTING_GUIDING = "starting_guiding"
    FOCUSING = "focusing"
    CHANGING_FILTER = "changing_filter"
    EXPOSING = "exposing"
    DITHERING = "dithering"
    WAITING_FOR_PRIMARY = "waiting_for_primary"
    WAITING_FOR_GUIDING = "waiting_for_guiding"
    MERIDIAN_FLIP = "meridian_flip"
    COOLING = "cooling"
    PARKING = "parking"
    WAITING = "waiting"


class RunOutcome(StrEnum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    CANCELLED = "cancelled"
    FAILED = "failed"


class StallKind(StrEnum):
    GUIDING = "guiding"
    CENTERING = "centering"
    AUTOFOCUS = "autofocus"


class Stall(BaseModel):
    """A sky-dependent step that keeps failing and is being retried."""

    kind: StallKind
    since: datetime
    attempts: int = 0
    last_error: str | None = None
    next_attempt_at: datetime | None = None


class Interruption(BaseModel):
    at: datetime
    kind: Literal["pause", "stop", "switch", "defer", "skip", "cancel", "crash"]
    actor: Actor
    reason: str | None = None
    stall_kind: StallKind | None = None


class GroupProgress(BaseModel):
    frames_done: int = 0


class LaneRuntime(BaseModel):
    lane_id: str
    groups: list[GroupProgress]
    current_group: int | None = None
    activity: Activity | None = None


class TaskRuntime(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    lanes: list[LaneRuntime] = []
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    resolved_ra: float | None = None
    resolved_dec: float | None = None
    stall: Stall | None = None
    interruptions: list[Interruption] = Field(default=[], description="Most recent last; capped")

    def frames_done(self) -> int:
        return sum(g.frames_done for lane in self.lanes for g in lane.groups)


class QueueEntry(BaseModel):
    task: ImagingTask
    runtime: TaskRuntime


class SequencerStatus(BaseModel):
    run_state: RunState = RunState.IDLE
    activity: Activity | None = None
    message: str | None = None
    current_task_id: str | None = None
    lanes: list[LaneRuntime] = []
    pause_reason: str | None = Field(default=None, description="'user' or the error that paused")
    pending_request: str | None = Field(
        default=None,
        description="A pause/stop/skip/switch waiting for its boundary, e.g. 'pause@frame'",
    )
    stall: Stall | None = None
    last_run_outcome: RunOutcome | None = None
    last_error: str | None = None
    session_id: str | None = None
    tasks_total: int = 0
    tasks_done: int = 0
    exposure_started_at: datetime | None = Field(
        default=None, description="Start of the primary lane's current exposure"
    )
    exposure_duration: float | None = None
    eta_s: float | None = Field(default=None, description="Remaining exposure time of the queue")


# ── Pre-flight ────────────────────────────────────────────────────────────────


class PreflightIssue(BaseModel):
    severity: Literal["error", "warning"]
    task_id: str | None = None
    lane_id: str | None = None
    code: str
    message: str


class PreflightReport(BaseModel):
    ok: bool
    issues: list[PreflightIssue] = []
