"""Sequencer plugin settings (implementation-specific; not part of the core interface)."""

from pydantic import BaseModel, Field


class SequencerSettings(BaseModel):
    # Mount lifecycle
    unpark_on_start: bool = True
    park_on_complete: bool = False

    # Guiding
    guide_settle_pixels: float = Field(default=1.5, gt=0)
    guide_settle_time_s: int = Field(default=10, ge=0)
    guide_settle_timeout_s: int = Field(default=60, ge=1)

    # Dither
    dither_pixels: float = Field(default=3.0, gt=0)
    dither_ra_only: bool = False

    # Meridian flip (owned by the sequencer while a run is active)
    meridian_flip_enabled: bool = True
    meridian_flip_ha_hours: float = Field(default=0.1, ge=0.0, le=2.0)
    center_after_flip: bool = True

    # Centering (passed to the platesolve plugin's center())
    center_tolerance_arcsec: float = Field(default=60.0, gt=0)
    center_max_attempts: int = Field(default=5, ge=1)
    center_exposure_s: float = Field(default=5.0, gt=0)
    center_binning: int = Field(default=2, ge=1, le=4)

    # Guiding loss and stalls
    guide_healthy_after_s: float = Field(
        default=10.0, ge=0, description="Continuous guiding needed before a new frame starts"
    )
    guide_retry_interval_s: float = Field(
        default=60.0, gt=0, description="Retry starting guiding this often while it's down"
    )
    recenter_after_guide_loss_min: float = Field(
        default=15.0, ge=0, description="Re-centre once when guiding has been down this long"
    )
    center_retry_interval_s: float = Field(
        default=120.0, gt=0, description="Retry centering this often when nothing solves"
    )
    stall_timeout_min: float | None = Field(
        default=None,
        gt=0,
        description="Give up on a stall after this long (task error policy); null = never",
    )
    uncount_if_unguided_s: float | None = Field(
        default=None,
        gt=0,
        description="Retake frames unguided for longer than this (file kept); null = count all",
    )

    # Autofocus (autofocus plugin; its own settings define the sweep)
    refocus_after_flip: bool = False
    autofocus_on_temp_delta: float | None = Field(
        default=None, gt=0, description="Refocus when the focuser temperature moved this much (°C)"
    )
    autofocus_every_min: float | None = Field(
        default=None, gt=0, description="Refocus after this many minutes"
    )
    autofocus_retry_interval_s: float = Field(
        default=300.0, gt=0, description="Retry a failed (no stars) autofocus this often"
    )

    # Session journal
    journal_dir: str | None = Field(
        default=None,
        description="Where session journals go; null = 'journal' next to the saved images",
    )

    # Resume behaviour
    recenter_after_pause_min: float = Field(default=10.0, ge=0)

    # Step timeouts
    slew_timeout_s: float = Field(default=300.0, gt=0)
    flip_timeout_s: float = Field(default=300.0, gt=0)
    park_timeout_s: float = Field(default=180.0, gt=0)
    exposure_timeout_margin_s: float = Field(default=120.0, gt=0)
