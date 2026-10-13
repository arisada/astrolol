"""Turns a star's offset from its lock position into guide pulses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from astrolol.devices.base.pulse import PulseDirection
from astrolol.plugins.guider.calibration import Calibration
from astrolol.plugins.guider.predictor import MotionPredictor

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
    """Per-axis proportional control with hysteresis (a share of the last correction is kept),
    plus drift prediction.

    A proportional correction alone always trails a steady drift (polar misalignment, a
    tracking rate slightly off): the star settles at the distance where the share corrected
    per frame equals the drift per frame, a pixel or more with long cycles. The controller
    therefore estimates, slowly, how fast the star moves on its own (the change of the error
    that the pulses sent do not explain) and adds the pulse that cancels that motion until
    the next frame.
    """

    def __init__(
        self,
        calibration: Calibration,
        ra: AxisSettings | None = None,
        dec: AxisSettings | None = None,
        dec_mode: DecMode = "auto",
        *,
        compensate_backlash: bool = False,
        last_dec_dir: int = 0,
        predict_drift: bool = True,
        predict_periodic: bool = True,
        pe_period_s: float | None = None,
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
        self.predict_drift = predict_drift
        # The star's own motion along RA (drift and the worm's periodic error) and Dec (drift).
        self.predictors = (MotionPredictor(pe_period_s, periodic=predict_periodic), MotionPredictor(periodic=False))
        self._cycle = 0.0  # seconds between corrections
        self._last: tuple[float, float, float] | None = None  # (time, RA error, Dec error)
        self._sent = (0.0, 0.0)  # West ms, North ms actually sent after the last measurement

    def reset(self) -> None:
        """Start afresh after a jump of the lock (a dither) or a gap: the drift learnt stays."""
        self._prev = (0.0, 0.0)
        self._compensated = 0
        self._resist_dir = self._resist_votes = 0
        self._last = None
        self._sent = (0.0, 0.0)

    @property
    def drift(self) -> list[float]:
        """The steady part of the star's own motion, axis pixels per second (RA, Dec)."""
        return [p.drift for p in self.predictors]

    def forget_drift(self) -> None:
        """The axes changed meaning (one was reversed): the motion learnt no longer applies."""
        self.reset()
        for p in self.predictors:
            p.reset()

    def pulses_failed(self, *, ra: bool = True, dec: bool = True) -> None:
        """The pulses of the last correction on these axes did not go out."""
        self._sent = (0.0 if ra else self._sent[0], 0.0 if dec else self._sent[1])

    def _learn_drift(self, now: float, ra_err: float, dec_err: float) -> None:
        last, self._last = self._last, (now, ra_err, dec_err)
        if last is None:
            return
        dt = now - last[0]
        if not 0 < dt < 60:
            return
        self._cycle = dt if self._cycle == 0 else self._cycle + 0.2 * (dt - self._cycle)
        c = self.calibration
        # Sending w ms West moves the RA error by w * rate (and North likewise for Dec).
        own = (
            (ra_err - last[1] - self._sent[0] * c.ra_rate) / dt,
            (dec_err - last[2] - self._sent[1] * c.dec_rate) / dt,
        )
        for predictor, rate in zip(self.predictors, own):
            predictor.add(last[0], now, rate)

    def _feed_forward(self, now: float | None) -> tuple[float, float]:
        """(West ms, North ms) cancelling the motion predicted until the next measurement."""
        if not self.predict_drift or now is None or self._cycle == 0:
            return 0.0, 0.0
        c = self.calibration
        ra, dec = (p.displacement(now, now + self._cycle) for p in self.predictors)
        return -ra / c.ra_rate, -dec / c.dec_rate

    def correct(self, dx: float, dy: float, now: float | None = None) -> list[tuple[PulseDirection, int]]:
        """Pulses for an error of (dx, dy) pixels measured at *now* (monotonic seconds; without
        it there is no drift prediction). Empty when there is nothing worth correcting."""
        ra_err, dec_err = self.calibration.axis_error(dx, dy)
        if now is not None:
            self._learn_drift(now, ra_err, dec_err)
        west, north = self.calibration.pulses_for(dx, dy)
        self._learn_overshoot(north, abs(dec_err))
        west = self._axis(west, abs(ra_err), self._prev[0], self.ra)
        north = self._axis(north, abs(dec_err), self._prev[1], self.dec)
        ff_west, ff_north = self._feed_forward(now)
        prev = (west, north)
        west = max(-self.ra.max_pulse_ms, min(self.ra.max_pulse_ms, west + ff_west))
        north = max(-self.dec.max_pulse_ms, min(self.dec.max_pulse_ms, north + ff_north))
        north = self._resist(north, abs(dec_err))
        if self.dec_mode == "off" or (self.dec_mode == "north" and north < 0) or (
            self.dec_mode == "south" and north > 0
        ):
            north = 0.0
        self._prev = (prev[0], prev[1] if north else 0.0)  # hysteresis keeps the proportional part
        north = self._compensate(north)
        pulses: list[tuple[PulseDirection, int]] = []
        sent_w = sent_n = 0.0
        if abs(west) >= self.ra.min_pulse_ms:
            pulses.append(("W" if west > 0 else "E", int(round(abs(west)))))
            sent_w = float(round(west))
        if abs(north) >= self.dec.min_pulse_ms:
            pulses.append(("N" if north > 0 else "S", int(round(abs(north)))))
            sent_n = float(round(north))
        # Slack taken up by a reversal moves nothing: count only what should move the star.
        if self._compensated and sent_n:
            sent_n -= self._compensated * min(self.backlash_share * self.calibration.dec_backlash_ms, abs(sent_n))
        self._sent = (sent_w, sent_n)
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
