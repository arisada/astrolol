"""PHD2-specific event models."""
from __future__ import annotations

from typing import Literal

from astrolol.core.events.models import BaseEvent


class Phd2Connected(BaseEvent):
    type: Literal["phd2.connected"] = "phd2.connected"


class Phd2Disconnected(BaseEvent):
    type: Literal["phd2.disconnected"] = "phd2.disconnected"


class Phd2StateChanged(BaseEvent):
    type: Literal["phd2.state_changed"] = "phd2.state_changed"
    state: str  # PHD2 AppState: Stopped, Guiding, Calibrating, Paused, etc.


class Phd2GuideStep(BaseEvent):
    type: Literal["phd2.guide_step"] = "phd2.guide_step"
    frame: int
    ra_dist: float    # arcsec (pixels × pixel_scale; raw pixels if scale unknown)
    dec_dist: float
    ra_corr: float    # guide pulse duration, ms
    dec_corr: float
    star_snr: float | None = None


class Phd2Settled(BaseEvent):
    type: Literal["phd2.settled"] = "phd2.settled"
    error: str | None = None  # None = success
