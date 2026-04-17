"""Pydantic models for the PHD2 plugin API."""
from pydantic import BaseModel, Field


class Phd2Status(BaseModel):
    connected: bool
    state: str  # PHD2 AppState string or "Disconnected"
    rms_ra: float | None = None    # arcsec (or pixels if pixel_scale unknown)
    rms_dec: float | None = None
    rms_total: float | None = None
    pixel_scale: float | None = None  # arcsec/px; None = not fetched yet
    star_snr: float | None = None
    is_dithering: bool = False
    debug_enabled: bool = False


class SettleParams(BaseModel):
    pixels: float = Field(default=1.5, gt=0, description="Settle threshold in guide pixels")
    time: int = Field(default=10, ge=0, description="Stability time required at threshold (s)")
    timeout: int = Field(default=60, ge=1, description="Maximum time to wait for settle (s)")


class GuideRequest(BaseModel):
    settle: SettleParams = SettleParams()
    recalibrate: bool = False


class DitherRequest(BaseModel):
    pixels: float = Field(default=5.0, gt=0, description="Dither amount in guide camera pixels")
    ra_only: bool = False
    settle: SettleParams = SettleParams()


class DebugRequest(BaseModel):
    enabled: bool
