"""Events published by the built-in guider."""
from __future__ import annotations

from typing import Literal

from astrolol.core.events.models import BaseEvent


class GuiderStep(BaseEvent):
    """One guide cycle: how far the star was from its lock and what the guider did about it."""

    type: Literal["guider.step"] = "guider.step"
    frame: int
    ra_dist: float  # arcsec (guide pixels when the pixel scale is unknown); positive = East
    dec_dist: float  # positive = North
    ra_corr: float  # pulse sent, ms: positive West, negative East, 0 = none
    dec_corr: float  # positive North, negative South
    star_snr: float | None = None
    stars_found: int = 0
    # What the controller added to the pulses of its own accord, to find out why a correction
    # was the size it was.
    drift_ra: float = 0.0  # learnt steady motion of the star, px/s (RA axis, then Dec)
    drift_dec: float = 0.0
    predicted_ra: float = 0.0  # part of the pulse that is prediction (drift, periodic error), ms, + West
    predicted_dec: float = 0.0  # + North
    pe_period: float | None = None  # period of the periodic-error model in use, s
    ra_rate: float = 0.0  # calibration in use: px per ms of pulse
    dec_rate: float = 0.0
