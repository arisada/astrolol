"""Plate-solving event models."""
from __future__ import annotations

from typing import Literal

from astrolol.core.events.models import BaseEvent


class PlatesolveStarted(BaseEvent):
    type: Literal["platesolve.started"] = "platesolve.started"
    solve_id: str
    fits_path: str


class PlatesolveCompleted(BaseEvent):
    type: Literal["platesolve.completed"] = "platesolve.completed"
    solve_id: str
    ra: float           # degrees J2000
    dec: float          # degrees J2000
    rotation: float     # degrees, North through East
    pixel_scale: float  # arcsec/pixel
    field_w: float      # degrees
    field_h: float      # degrees
    duration_ms: int


class PlatesolveFailed(BaseEvent):
    type: Literal["platesolve.failed"] = "platesolve.failed"
    solve_id: str
    reason: str


class PlatesolveCancelled(BaseEvent):
    type: Literal["platesolve.cancelled"] = "platesolve.cancelled"
    solve_id: str


class PlatesolveCenterStarted(BaseEvent):
    type: Literal["platesolve.center_started"] = "platesolve.center_started"
    run_id: str
    ra: float           # target, degrees
    dec: float
    tolerance_arcsec: float


class PlatesolveCenterAttempt(BaseEvent):
    type: Literal["platesolve.center_attempt"] = "platesolve.center_attempt"
    run_id: str
    attempt: int
    solved_ra: float | None = None
    solved_dec: float | None = None
    error_arcsec: float | None = None
    solve_error: str | None = None
    duration_s: float


class PlatesolveCenterFinished(BaseEvent):
    type: Literal["platesolve.center_finished"] = "platesolve.center_finished"
    run_id: str
    success: bool
    failure: str | None = None
    final_error_arcsec: float | None = None
    message: str | None = None
