"""Pydantic models for the plate-solving plugin API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SolveRequest(BaseModel):
    fits_path: str
    ra_hint: float | None = Field(default=None, description="RA hint in degrees (J2000)")
    dec_hint: float | None = Field(default=None, description="Dec hint in degrees (J2000)")
    radius: float = Field(default=30.0, gt=0, description="Search radius in degrees")
    fov: float | None = Field(default=None, gt=0, description="Field width in degrees (None = auto)")


class SolveResult(BaseModel):
    ra: float           # degrees J2000
    dec: float          # degrees J2000
    rotation: float     # degrees, North through East
    pixel_scale: float  # arcsec/pixel
    field_w: float      # degrees
    field_h: float      # degrees
    duration_ms: int = 0


SolveJobStatus = Literal["pending", "solving", "completed", "failed", "cancelled"]


class SolveJob(BaseModel):
    id: str
    status: SolveJobStatus
    request: SolveRequest
    result: SolveResult | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
