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
    mount_id: str | None = None  # connected mount (needed for the "mount" output)
    exposure: float = Field(default=1.0, gt=0, description="Guide exposure (s)")
    gain: int | None = None
    pixel_scale: float | None = Field(default=None, gt=0, description="arcsec per guide pixel")
    star_count: int = Field(default=3, ge=1, le=6, description="Guide star plus companions")
    dec_backlash_compensation: bool = Field(
        default=True, description="Add the measured Dec backlash to the first pulse after Dec reverses"
    )
    calibration_steps: int = Field(default=6, ge=3, le=20)
    lost_timeout_s: float = Field(default=60.0, gt=0, description="Give up after the star is lost this long")


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
