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


# ── What to do about a doubtful result ────────────────────────────────────────

# warn: keep the result and flag it (a run with no usable fit still fails); retry: measure again;
# fail: stop, and put the focuser back where it started.
FocusAction = Literal["warn", "retry", "fail"]


class DoubtPolicy(BaseModel):
    """How a run reacts to each cause of a doubtful result (see quality.py)."""
    on_edge: FocusAction = Field(
        default="retry",
        description="The minimum is not bracketed: sweep again around the best position "
        "(at most twice, on top of max_retries).",
    )
    on_flat: FocusAction = Field(default="retry", description="The sharpness hardly changes over the sweep.")
    on_noisy: FocusAction = Field(default="retry", description="The samples do not follow a V.")
    on_few_stars: FocusAction = Field(default="retry", description="Too many steps found too few stars.")
    max_retries: int = Field(
        default=2, ge=0, le=5,
        description="Complete new sweeps, with a longer exposure, for a flat, noisy or starless curve.",
    )
    retry_exposure_factor: float = Field(
        default=2.0, ge=1.0, le=4.0, description="Exposure of a retry, as a multiple of the previous one.",
    )
    max_exposure: float = Field(
        default=16.0, gt=0, description="Longest exposure a retry may use, in seconds.",
    )


# ── Persistent UI settings (stored in plugin_settings['autofocus']) ────────────

class AutofocusSettings(DoubtPolicy):
    """User-facing parameters, saved as they are changed. The sequencer runs its autofocus with them."""
    camera_id: str | None = Field(default=None, description="Camera last chosen on the page")
    step_size: int = Field(default=100, gt=0)
    num_steps: int = Field(default=5, ge=3, le=15)
    exposure_time: float = Field(default=2.0, gt=0)
    binning: int = Field(default=1, ge=1, le=4)
    gain: int | None = None
    filter_slot: int | None = None
    fit_algo: Literal["parabola", "hyperbola"] = "parabola"
    metric: Literal["fwhm", "hfd"] = "hfd"
    lock_stars: bool = Field(
        default=False,
        description="Keep measuring the same stars detected on the first exposure "
        "(preferred, not required — a star that drops below the detection floor "
        "as it defocuses is just skipped for that step) instead of a fresh "
        "unrelated population each step.",
    )


# ── Configuration ─────────────────────────────────────────────────────────────

class AutofocusConfig(DoubtPolicy):
    camera_id: str
    focuser_id: str
    step_size: int = Field(default=100, gt=0, description="Focuser steps between sample positions")
    num_steps: int = Field(default=5, ge=3, le=15, description="Steps each side of starting position")
    exposure_time: float = Field(default=2.0, gt=0, description="Exposure duration in seconds")
    binning: int = Field(default=1, ge=1, le=4)
    gain: int | None = None
    filter_slot: int | None = Field(default=None, description="Filter slot to select before run (None = keep current)")
    filter_wheel_id: str | None = Field(
        default=None,
        description="Filter wheel to select the slot on. None = whichever filter wheel is "
        "connected (only correct with exactly one on the whole rig).",
    )
    start_position: int | None = Field(
        default=None,
        ge=0,
        description="Focuser position to move to before sweeping. None = use the focuser's "
        "current position as the centre of the sweep.",
    )
    fit_algo: Literal["parabola", "hyperbola"] = "parabola"
    metric: Literal["fwhm", "hfd"] = "hfd"
    lock_stars: bool = Field(
        default=False,
        description="Keep measuring the same stars detected on the first exposure "
        "instead of a fresh population each step (see AutofocusSettings.lock_stars).",
    )


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
    r_squared: float | None = None


# What makes a result doubtful (see quality.py): the minimum is not bracketed, the curve is flat,
# the samples do not follow a V, or too many steps found no stars.
Cause = Literal["edge", "flat", "noisy", "few_stars"]


class FitMetrics(BaseModel):
    """The numbers the verdict rests on."""
    r_squared: float | None = None
    spread: float | None = None      # worst / best sharpness among the usable samples
    below: int = 0                   # usable samples below the optimum
    above: int = 0                   # usable samples above the optimum
    valid_points: int = 0
    sampled_points: int = 0


class FocusQuality(BaseModel):
    verdict: Literal["good", "poor"]
    causes: list[Cause] = []
    metrics: FitMetrics = FitMetrics()


AutofocusRunStatus = Literal["running", "completed", "failed", "aborted"]


class FocusAttempt(BaseModel):
    """A sweep that was judged doubtful and measured again."""
    exposure_time: float
    data_points: list[FocusDataPoint]
    quality: FocusQuality


class AutofocusRun(BaseModel):
    id: str = Field(default_factory=_uid)
    config: AutofocusConfig
    status: AutofocusRunStatus = "running"
    current_step: int = 0
    total_steps: int = 0
    data_points: list[FocusDataPoint] = []
    curve_fit: CurveFit | None = None
    optimal_position: int | None = None
    # How far the result can be trusted, set when the run completes.
    quality: FocusQuality | None = None
    # Exposure of the sweep in progress or last made (longer than config.exposure_time after a retry).
    exposure_time: float | None = None
    # Sweeps given up on for a doubtful curve, before the one in data_points.
    attempts: list[FocusAttempt] = []
    # Where the focuser was before the run touched it (a manual start_position does not change this).
    initial_position: int | None = None
    error: str | None = None
    # True when the run failed because of the sky (no stars found), not the hardware:
    # a sequencer retries those later instead of treating them as errors.
    sky_problem: bool = False
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
    quality: Literal["good", "poor"] | None = None
    causes: list[Cause] = []


class AutofocusAbortedEvent(BaseEvent):
    type: Literal["autofocus.aborted"] = "autofocus.aborted"
    run_id: str


class AutofocusFailedEvent(BaseEvent):
    type: Literal["autofocus.failed"] = "autofocus.failed"
    run_id: str
    reason: str
