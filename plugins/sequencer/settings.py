"""Sequencer plugin settings."""
from pydantic import BaseModel


class SequencerSettings(BaseModel):
    # Mount lifecycle
    unpark_on_start: bool = True
    park_on_complete: bool = False

    # Guiding
    stop_guide_before_slew: bool = True
    restart_guide_after_slew: bool = True

    # Meridian flip (checked at every frame boundary)
    meridian_flip_enabled: bool = True
    meridian_flip_ha_threshold: float = 0.1   # hours past meridian to trigger flip
    plate_solve_after_flip: bool = True
    refocus_after_flip: bool = False           # STUB

    # Autofocus (all STUB — no autofocus plugin yet)
    autofocus_before_start: bool = False
    autofocus_on_temp_delta: float | None = 2.0   # °C change triggers refocus
    autofocus_on_time_min: float | None = None    # minutes elapsed

    # Guiding settle
    guide_settle_time_s: int = 10
    guide_settle_timeout_s: int = 60

    # Dither
    dither_pixels: float = 3.0
    dither_ra_only: bool = False

    # Plate solve exposure for sequencer (short, unsaved)
    plate_solve_duration_s: float = 5.0
