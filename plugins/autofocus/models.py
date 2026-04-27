"""Pydantic models and WebSocket events for the autofocus plugin."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from astrolol.core.events.models import BaseEvent


def _uid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Configuration ─────────────────────────────────────────────────────────────

class AutofocusConfig(BaseModel):
    camera_id: str
    focuser_id: str
    step_size: int = Field(default=100, gt=0, description="Focuser steps between sample positions")
    num_steps: int = Field(default=5, ge=3, le=15, description="Steps each side of starting position")
    exposure_time: float = Field(default=2.0, gt=0, description="Exposure duration in seconds")
    binning: int = Field(default=1, ge=1, le=4)
    gain: int | None = None
    filter_slot: int | None = Field(default=None, description="Filter slot to select before run (None = keep current)")


# ── Result types ──────────────────────────────────────────────────────────────

class StarInfo(BaseModel):
    """Centroid and FWHM of a single detected star, in image pixel coordinates."""
    x: float
    y: float
    fwhm: float


class FocusDataPoint(BaseModel):
    """Measured FWHM at a single focuser position."""
    step: int           # 1-indexed step number
    position: int       # focuser step position
    fwhm: float         # median FWHM in pixels (0 if no stars detected)
    star_count: int


class CurveFit(BaseModel):
    """Fitted parabola y = a·x² + b·x + c with the derived optimal position."""
    a: float
    b: float
    c: float
    optimal_position: float


AutofocusRunStatus = Literal["running", "completed", "failed", "aborted"]


class AutofocusRun(BaseModel):
    id: str = Field(default_factory=_uid)
    config: AutofocusConfig
    status: AutofocusRunStatus = "running"
    current_step: int = 0
    total_steps: int = 0
    data_points: list[FocusDataPoint] = []
    curve_fit: CurveFit | None = None
    optimal_position: int | None = None
    error: str | None = None
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    # Latest step image metadata (for the star-overlay UI panel)
    latest_stars: list[StarInfo] = []
    image_width: int | None = None
    image_height: int | None = None


# ── WebSocket events ──────────────────────────────────────────────────────────

class AutofocusStartedEvent(BaseEvent):
    type: Literal["autofocus.started"] = "autofocus.started"
    run_id: str
    camera_id: str
    focuser_id: str
    total_steps: int


class AutofocusDataPointEvent(BaseEvent):
    """Emitted after each step with the measured FWHM."""
    type: Literal["autofocus.data_point"] = "autofocus.data_point"
    run_id: str
    step: int
    total_steps: int
    position: int
    fwhm: float
    star_count: int


class AutofocusCompletedEvent(BaseEvent):
    type: Literal["autofocus.completed"] = "autofocus.completed"
    run_id: str
    optimal_position: int


class AutofocusAbortedEvent(BaseEvent):
    type: Literal["autofocus.aborted"] = "autofocus.aborted"
    run_id: str


class AutofocusFailedEvent(BaseEvent):
    type: Literal["autofocus.failed"] = "autofocus.failed"
    run_id: str
    reason: str
