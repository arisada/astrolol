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
