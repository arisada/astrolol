"""Guide simulator settings."""

from pydantic import BaseModel, Field


class GuideSimSettings(BaseModel):
    connected_at_startup: bool = True
    rms_arcsec: float = Field(default=0.8, gt=0, description="Total guiding RMS while guiding")
    pixel_scale: float = Field(default=1.5, gt=0, description="Arcsec per guide pixel")
    step_interval_s: float = Field(default=2.0, gt=0, description="Guide exposure cadence")
    settle_extra_s: float = Field(
        default=3.0, ge=0, description="Time to settle on top of the requested settle time"
    )
    lose_star_on_slew: bool = Field(
        default=True, description="A slew while guiding loses the star and stops guiding"
    )
    time_scale: float = Field(
        default=1.0, gt=0, description="Multiplier for every simulated duration (tests use ≪ 1)"
    )
