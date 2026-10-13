"""Guider settings and the choice of where guide pulses go."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from astrolol.devices.base.interfaces import IPulseGuider
from astrolol.devices.base.pulse import PulseGuideNotSupported

GuideOutput = Literal["camera", "mount"]


class GuiderSettings(BaseModel):
    # "camera": pulses leave through the guide camera's ST4 output.
    # "mount": pulses go to the mount over its own connection.
    guide_output: GuideOutput = "camera"
    camera_id: str | None = None  # connected camera used for guiding
    # Connected mount: needed for the "mount" output; with the camera output it is only asked
    # where it points (declination, pier side) and whether it is slewing. None: the only one.
    mount_id: str | None = None
    exposure: float = Field(default=1.0, gt=0, description="Guide exposure (s)")
    gain: int | None = None
    pixel_scale: float | None = Field(default=None, gt=0, description="arcsec per guide pixel")
    star_count: int = Field(default=3, ge=1, le=6, description="Guide star plus companions")
    dec_backlash_compensation: bool = Field(
        default=False, description="Add the measured Dec backlash to the first pulse after Dec reverses"
    )
    dec_resist_reversals: bool = Field(
        default=True, description="Reverse Dec only when several frames in a row, or one large error, ask for it"
    )
    calibration_steps: int = Field(default=6, ge=3, le=20)
    calibration_travel_px: float = Field(default=25.0, ge=5, le=100, description="How far calibration moves the star")
    # After a meridian flip West always moves the star the other way on the sensor. North does
    # too when the mount's driver follows the sky ("mount" output, usually), not through an
    # ST4 cable. "auto" guesses from the output; a wrong guess is caught while guiding.
    flip_dec_after_meridian_flip: Literal["auto", "yes", "no"] = "auto"
    lost_timeout_s: float = Field(
        default=0.0, ge=0, description="Give up after the star is lost this long (0: keep looking)"
    )
    # Control loop.
    ra_aggressiveness: float = Field(default=0.7, gt=0, le=1.0)
    ra_hysteresis: float = Field(default=0.1, ge=0, lt=1.0)
    dec_aggressiveness: float = Field(default=0.6, gt=0, le=1.0)
    min_move_px: float | None = Field(
        default=None, ge=0, description="Errors below this are left alone (None: from the pixel scale)"
    )
    max_pulse_ms: int = Field(default=2000, ge=50, le=10_000)
    min_pulse_ms: int = Field(default=20, ge=1, le=500)
    dec_mode: Literal["auto", "north", "south", "off"] = "auto"
    predict_drift: bool = Field(default=True, description="Learn the steady drift and correct it ahead")


def auto_min_move_px(pixel_scale: float | None) -> float:
    """A minimum move that ignores seeing: about 0.3 arcsec, between 0.1 and 0.5 pixel."""
    if not pixel_scale:
        return 0.15
    return max(0.1, min(0.5, 0.3 / pixel_scale))


def pick_pulse_guider(
    output: GuideOutput, camera: object | None, mount: object | None
) -> IPulseGuider:
    """The device that should receive guide pulses; raises PulseGuideNotSupported if it can't."""
    device, label = (camera, "guide camera") if output == "camera" else (mount, "mount")
    if device is None:
        raise PulseGuideNotSupported(f"no {label} is connected")
    if not isinstance(device, IPulseGuider):
        raise PulseGuideNotSupported(f"the {label} cannot pulse guide")
    return device
