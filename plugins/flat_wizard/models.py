"""Pydantic models and WebSocket events for the flat calibration wizard."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from astrolol.core.events.models import BaseEvent


def _uid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Configuration ─────────────────────────────────────────────────────────────

class FlatWizardFilterSpec(BaseModel):
    """One filter (or the single pass for a camera with no filter wheel) to solve for."""
    filter_name: str | None = Field(
        default=None, description="Filter wheel slot name; null = no filter wheel / don't touch it"
    )
    count: int = Field(ge=1, description="Number of flat frames to queue for this filter")


class FlatWizardCameraSpec(BaseModel):
    """One camera to shoot flats with, and which of its filters."""
    camera_id: str
    filter_wheel_id: str | None = Field(
        default=None, description="Filter wheel to use; null = camera has none (single pass only)"
    )
    filters: list[FlatWizardFilterSpec] = Field(min_length=1)
    gain: int | None = Field(default=None, ge=0, description="None = leave driver gain unchanged")


class FlatWizardConfig(BaseModel):
    cameras: list[FlatWizardCameraSpec] = Field(
        min_length=1,
        description="Cameras are solved concurrently and queued as parallel sequencer lanes",
    )

    @field_validator("cameras")
    @classmethod
    def _unique_cameras(cls, cameras: list[FlatWizardCameraSpec]) -> list[FlatWizardCameraSpec]:
        ids = [c.camera_id for c in cameras]
        if len(set(ids)) != len(ids):
            raise ValueError("Each camera may appear only once")
        return cameras
    target_pct: float = Field(
        default=50.0, gt=0, lt=100,
        description="Target mean level as a percentage of the sensor's full-scale ADU",
    )
    tolerance_pct: float = Field(
        default=5.0, gt=0, lt=50, description="Acceptable +/- band around target_pct"
    )
    saturation_pct: float = Field(
        default=95.0, gt=0, le=100,
        description="Mean level (as % of full-scale) at or above which a trial is treated as "
        "saturated/clipped and retried at a much shorter duration, regardless of target_pct",
    )
    binning: int = Field(default=1, ge=1, le=4)
    seed_duration: float = Field(default=0.01, gt=0, description="Starting trial exposure duration, seconds")
    min_duration: float = Field(default=0.001, gt=0, description="Lower safety bound for trial exposures")
    max_duration: float = Field(default=30.0, gt=0, description="Upper safety bound for trial exposures")
    max_attempts: int = Field(default=8, ge=1, le=20, description="Trial exposures allowed per filter")


# ── Result types ──────────────────────────────────────────────────────────────

class FlatTrial(BaseModel):
    """One trial exposure's measured result."""
    attempt: int
    duration: float
    mean_adu: float
    full_scale_adu: float
    ratio_pct: float
    saturated: bool


FlatFilterStatus = Literal["solved", "failed"]


class FlatFilterResult(BaseModel):
    camera_id: str
    filter_name: str | None
    status: FlatFilterStatus
    solved_duration: float | None = None
    trials: list[FlatTrial] = []
    error: str | None = None


FlatWizardRunStatus = Literal["running", "completed", "failed", "aborted"]


class FlatWizardRun(BaseModel):
    id: str = Field(default_factory=_uid)
    config: FlatWizardConfig
    status: FlatWizardRunStatus = "running"
    total_filters: int = Field(default=0, description="Camera/filter combinations to solve")
    results: list[FlatFilterResult] = Field(
        default=[], description="In completion order — cameras are solved concurrently",
    )
    task_id: str | None = Field(default=None, description="The sequencer task id once queued")
    error: str | None = None
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None


# ── WebSocket events ──────────────────────────────────────────────────────────

class FlatWizardStartedEvent(BaseEvent):
    type: Literal["flat_wizard.started"] = "flat_wizard.started"
    run_id: str
    camera_ids: list[str]
    total_filters: int


class FlatWizardTrialEvent(BaseEvent):
    """Emitted after each trial exposure with the measured ADU level."""
    type: Literal["flat_wizard.trial"] = "flat_wizard.trial"
    run_id: str
    camera_id: str
    filter_index: int       # index of the camera/filter combination in the run
    filter_name: str | None
    attempt: int
    duration: float
    mean_adu: float
    full_scale_adu: float
    ratio_pct: float
    saturated: bool


class FlatWizardFilterSolvedEvent(BaseEvent):
    type: Literal["flat_wizard.filter_solved"] = "flat_wizard.filter_solved"
    run_id: str
    camera_id: str
    filter_index: int
    filter_name: str | None
    duration: float


class FlatWizardFilterFailedEvent(BaseEvent):
    type: Literal["flat_wizard.filter_failed"] = "flat_wizard.filter_failed"
    run_id: str
    camera_id: str
    filter_index: int
    filter_name: str | None
    error: str


class FlatWizardCompletedEvent(BaseEvent):
    type: Literal["flat_wizard.completed"] = "flat_wizard.completed"
    run_id: str
    task_id: str | None


class FlatWizardFailedEvent(BaseEvent):
    type: Literal["flat_wizard.failed"] = "flat_wizard.failed"
    run_id: str
    reason: str


class FlatWizardAbortedEvent(BaseEvent):
    type: Literal["flat_wizard.aborted"] = "flat_wizard.aborted"
    run_id: str
