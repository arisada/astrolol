"""Turns a star's offset from its lock position into guide pulses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from astrolol.devices.base.pulse import PulseDirection
from astrolol.plugins.guider.calibration import Calibration

SWITCH_FRAMES = 3  # consecutive frames asking to reverse before a resisting axis gives in
FAST_SWITCH_FACTOR = 3.0  # an error this many times the minimum move reverses at once
OVERSHOOT_SHRINK = 0.6  # backlash share kept after a compensated pulse overshoots

DecMode = Literal["auto", "north", "south", "off"]


class AxisSettings(BaseModel):
    aggressiveness: float = Field(default=0.7, gt=0, le=1.0, description="Share of the error corrected per frame")
    hysteresis: float = Field(default=0.1, ge=0, lt=1.0, description="Weight of the previous correction")
    min_move_px: float = Field(default=0.15, ge=0, description="Errors below this are left alone")
    max_pulse_ms: int = Field(default=2000, gt=0)
    min_pulse_ms: int = Field(default=20, ge=1, description="Shorter pulses are not sent; the error builds up instead")
    resist_switch: bool = Field(default=False, description="Only reverse after several frames asking for it")
    fast_switch: bool = Field(default=True, description="...unless the error is large (3x the minimum move)")


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
        # The backlash measured at calibration is only an estimate (a mount's pulse latency looks
        # like backlash too). The share of it that is applied shrinks whenever a compensated
        # pulse overshoots, so a wrong estimate dies out instead of making Dec ring forever.
        self.backlash_share = 1.0
        self._compensated = 0  # direction of the last Dec pulse if it carried compensation
        self._resist_dir = 0  # direction Dec was last allowed to correct in
        self._resist_votes = 0  # consecutive frames asking for the other direction

    def reset(self) -> None:
        self._prev = (0.0, 0.0)
        self._compensated = 0
        self._resist_dir = self._resist_votes = 0

    def correct(self, dx: float, dy: float) -> list[tuple[PulseDirection, int]]:
        """Pulses for an error of (dx, dy) pixels. Empty when the error is within tolerance."""
        ra_err, dec_err = self.calibration.axis_error(dx, dy)
        west, north = self.calibration.pulses_for(dx, dy)
        self._learn_overshoot(north, abs(dec_err))
        west = self._axis(west, abs(ra_err), self._prev[0], self.ra)
        north = self._axis(north, abs(dec_err), self._prev[1], self.dec)
        north = self._resist(north, abs(dec_err))
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

    def _resist(self, north: float, err_px: float) -> float:
        """Dec reversals cost backlash, so they need evidence: several frames in a row asking for the
        other direction, or one large error. Anything else is seeing, and is left alone."""
        s = self.dec
        if not s.resist_switch or north == 0:
            return north
        sign = 1 if north > 0 else -1
        if self._resist_dir in (0, sign):
            self._resist_dir, self._resist_votes = sign, 0
            return north
        self._resist_votes += 1
        if self._resist_votes >= SWITCH_FRAMES or (s.fast_switch and err_px >= FAST_SWITCH_FACTOR * s.min_move_px):
            self._resist_dir, self._resist_votes = sign, 0
            return north
        return 0.0

    def _learn_overshoot(self, north_now: float, dec_err_px: float) -> None:
        """A compensated pulse that left the star on the other side of its lock was too long."""
        sent, self._compensated = self._compensated, 0
        if sent and north_now * sent < 0 and dec_err_px >= self.dec.min_move_px:
            self.backlash_share *= OVERSHOOT_SHRINK

    def _compensate(self, north: float) -> float:
        """Lengthen a Dec pulse that reverses direction by the backlash measured at calibration."""
        if north == 0:
            return 0.0
        sign = 1 if north > 0 else -1
        compensated = north
        if self.compensate_backlash and self._dec_dir not in (0, sign):
            compensated += sign * min(self.backlash_share * self.calibration.dec_backlash_ms, self.dec.max_pulse_ms)
            self._compensated = sign
        if abs(compensated) >= self.dec.min_pulse_ms:
            self._dec_dir = sign  # a pulse really goes out
        return compensated

    @staticmethod
    def _axis(full_ms: float, err_px: float, prev_ms: float, s: AxisSettings) -> float:
        if err_px < s.min_move_px:
            return 0.0
        ms = s.aggressiveness * ((1 - s.hysteresis) * full_ms + s.hysteresis * prev_ms)
        return max(-s.max_pulse_ms, min(s.max_pulse_ms, ms))
