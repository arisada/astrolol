"""Turns a star's offset from its lock position into guide pulses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from astrolol.devices.base.pulse import PulseDirection
from plugins.guider.calibration import Calibration

DecMode = Literal["auto", "north", "south", "off"]


class AxisSettings(BaseModel):
    aggressiveness: float = Field(default=0.7, gt=0, le=1.0, description="Share of the error corrected per frame")
    hysteresis: float = Field(default=0.1, ge=0, lt=1.0, description="Weight of the previous correction")
    min_move_px: float = Field(default=0.15, ge=0, description="Errors below this are left alone")
    max_pulse_ms: int = Field(default=2000, gt=0)
    min_pulse_ms: int = Field(default=20, ge=1, description="Shorter pulses are not sent; the error builds up instead")


class GuideController:
    """Per-axis proportional control with hysteresis (a share of the last correction is kept)."""

    def __init__(
        self,
        calibration: Calibration,
        ra: AxisSettings | None = None,
        dec: AxisSettings | None = None,
        dec_mode: DecMode = "auto",
        *,
        compensate_backlash: bool = False,
        last_dec_dir: int = 0,
    ) -> None:
        self.calibration = calibration
        self.ra = ra or AxisSettings()
        self.dec = dec or AxisSettings(aggressiveness=0.6)
        self.dec_mode = dec_mode
        self._prev = (0.0, 0.0)  # last commanded (West ms, North ms), before backlash compensation
        self.compensate_backlash = compensate_backlash
        # Direction of the last Dec pulse sent (+1 North, -1 South, 0 unknown): when the next one
        # goes the other way, the gears must first take up the slack.
        self._dec_dir = last_dec_dir

    def reset(self) -> None:
        self._prev = (0.0, 0.0)

    def correct(self, dx: float, dy: float) -> list[tuple[PulseDirection, int]]:
        """Pulses for an error of (dx, dy) pixels. Empty when the error is within tolerance."""
        ra_err, dec_err = self.calibration.axis_error(dx, dy)
        west, north = self.calibration.pulses_for(dx, dy)
        west = self._axis(west, abs(ra_err), self._prev[0], self.ra)
        north = self._axis(north, abs(dec_err), self._prev[1], self.dec)
        if self.dec_mode == "off" or (self.dec_mode == "north" and north < 0) or (
            self.dec_mode == "south" and north > 0
        ):
            north = 0.0
        self._prev = (west, north)
        north = self._compensate(north)
        pulses: list[tuple[PulseDirection, int]] = []
        if abs(west) >= self.ra.min_pulse_ms:
            pulses.append(("W" if west > 0 else "E", int(round(abs(west)))))
        if abs(north) >= self.dec.min_pulse_ms:
            pulses.append(("N" if north > 0 else "S", int(round(abs(north)))))
        return pulses

    def _compensate(self, north: float) -> float:
        """Lengthen a Dec pulse that reverses direction by the backlash measured at calibration."""
        if north == 0:
            return 0.0
        sign = 1 if north > 0 else -1
        compensated = north
        if self.compensate_backlash and self._dec_dir not in (0, sign):
            compensated += sign * min(self.calibration.dec_backlash_ms, self.dec.max_pulse_ms)
        if abs(compensated) >= self.dec.min_pulse_ms:
            self._dec_dir = sign  # a pulse really goes out
        return compensated

    @staticmethod
    def _axis(full_ms: float, err_px: float, prev_ms: float, s: AxisSettings) -> float:
        if err_px < s.min_move_px:
            return 0.0
        ms = s.aggressiveness * ((1 - s.hysteresis) * full_ms + s.hysteresis * prev_ms)
        return max(-s.max_pulse_ms, min(s.max_pulse_ms, ms))
