"""Public data contract of a guider (PHD2, the guide simulator, a future built-in guider)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SettleParams(BaseModel):
    pixels: float = Field(default=1.5, gt=0, description="Settle threshold in guide pixels")
    time: int = Field(
        default=10, ge=0, description="Time the error must stay below the threshold (s)"
    )
    timeout: int = Field(default=60, ge=1, description="Give up settling after this long (s)")


class GuiderStatus(BaseModel):
    guider: str  # implementation: "phd2", "simulator", …
    connected: bool
    state: str  # implementation-specific state text, for display
    guiding: bool  # valid guide steps are arriving right now
    active: bool  # guiding or trying to (capture running): stop it before slewing
    settling: bool = False
    pixel_scale: float | None = None  # arcsec per guide pixel, when known


class GuidingHealth(BaseModel):
    """Is guiding active right now (valid guide steps arriving)?"""

    guiding: bool
    guiding_for_s: float | None = None  # continuous guiding so far
    unguided_for_s: float | None = None  # time since guiding stopped / the star was lost
    reason: str | None = None  # star_lost, stopped, paused, disconnected, …


class GuidingStats(BaseModel):
    """Guiding quality over a time window (e.g. one exposure)."""

    duration_s: float
    steps: int
    rms_ra: float | None = None  # arcsec (guide pixels if the pixel scale is unknown)
    rms_dec: float | None = None
    rms_total: float | None = None
    unguided_s: float  # seconds of the window without active guiding
    losses: int  # times active guiding was interrupted in the window
