"""Calibration: how guide pulses move the star on the sensor.

The result is a 2x2 matrix, not an angle and a rate per axis. Column 0 is the star's move
(pixels) per millisecond of West pulse, column 1 per millisecond of North pulse. That covers
any camera rotation, mirroring (a meridian flip, a diagonal) and slightly non-orthogonal axes
without special cases: a correction is the solution of ``M @ pulses = -error``.
"""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable, Callable

import numpy as np
from pydantic import BaseModel

from astrolol.core.guiding.errors import GuiderError
from astrolol.devices.base.pulse import PulseDirection


class CalibrationFailed(GuiderError):
    pass


class Calibration(BaseModel):
    ra_x: float  # pixels per ms of West pulse (East is the opposite)
    ra_y: float
    dec_x: float  # pixels per ms of North pulse (South is the opposite)
    dec_y: float
    dec_backlash_ms: float = 0.0  # pulse time lost reversing Dec during calibration

    @property
    def matrix(self) -> np.ndarray:
        return np.array([[self.ra_x, self.dec_x], [self.ra_y, self.dec_y]])

    @property
    def ra_rate(self) -> float:
        """Pixels per ms along the RA axis."""
        return math.hypot(self.ra_x, self.ra_y)

    @property
    def dec_rate(self) -> float:
        return math.hypot(self.dec_x, self.dec_y)

    def pulses_for(self, dx: float, dy: float) -> tuple[float, float]:
        """(West ms, North ms) that would bring a star back from an error of (dx, dy) pixels."""
        a, b = np.linalg.solve(self.matrix, (-dx, -dy))
        return float(a), float(b)

    def axis_error(self, dx: float, dy: float) -> tuple[float, float]:
        """The error as (RA pixels, Dec pixels): positive RA means East of the lock."""
        a, b = self.pulses_for(dx, dy)
        return -a * self.ra_rate, -b * self.dec_rate

    def sensor_shift(self, ra_px: float, dec_px: float) -> tuple[float, float]:
        """Sensor displacement for a move of (ra_px West-positive, dec_px North-positive)."""
        v = self.matrix @ (ra_px / self.ra_rate, dec_px / self.dec_rate)
        return float(v[0]), float(v[1])


Measure = Callable[[], Awaitable[tuple[float, float]]]
Pulse = Callable[[PulseDirection, int], Awaitable[None]]


Timed = Callable[[], Awaitable[tuple[float, float, float]]]
Drift = tuple[float, float]  # pixels per second


def _timed(measure: Measure, clock: Callable[[], float]) -> Timed:
    async def timed() -> tuple[float, float, float]:
        x, y = await measure()
        return x, y, clock()

    return timed


async def _drift(measure: Timed, samples: int) -> Drift:
    """The star's drift with no pulses (a mount never tracks perfectly), by a straight-line fit."""
    pts = [await measure() for _ in range(samples)]
    t = np.array([p[2] for p in pts]) - pts[0][2]
    if t[-1] <= 0:
        return 0.0, 0.0
    vx = float(np.polyfit(t, [p[0] for p in pts], 1)[0])
    vy = float(np.polyfit(t, [p[1] for p in pts], 1)[0])
    return vx, vy


async def _probe(
    measure: Timed, pulse: Pulse, direction: PulseDirection, *, target_px: float, max_ms: int, drift: Drift
) -> int:
    """A pulse length that moves the star about *target_px*.

    Starts small: with a long focal length a one-second pulse can throw the star out of the
    window we track. The probe's own move is discarded (it also takes up any slack).
    """
    ms = 150
    for _ in range(5):
        x0, y0, t0 = await measure()
        await pulse(direction, ms)
        x1, y1, t1 = await measure()
        moved = math.hypot(x1 - x0 - drift[0] * (t1 - t0), y1 - y0 - drift[1] * (t1 - t0))
        if moved >= 0.7:
            return int(min(max(ms * target_px / moved, 50), max_ms))
        ms = min(ms * 4, max_ms)
    raise CalibrationFailed(f"the star did not move with {direction} pulses")


async def _return(
    measure: Timed, pulse: Pulse, direction: PulseDirection, steps: int, step_ms: int
) -> None:
    """Pulse back the way we came, a step at a time so the tracked window keeps up."""
    for _ in range(steps):
        await pulse(direction, step_ms)
        await measure()


async def _sweep(
    measure: Timed,
    pulse: Pulse,
    direction: PulseDirection,
    steps: int,
    step_ms: int,
    drift: Drift,
) -> tuple[float, float, float]:
    """Pulse *steps* times; returns (x per ms, y per ms, ms lost to slack at the start)."""
    moves: list[tuple[int, float, float]] = []  # (ms, dx, dy) of each pulse
    x0, y0, t0 = await measure()
    for _ in range(steps):
        await pulse(direction, step_ms)
        x1, y1, t1 = await measure()
        # What the pulse did: the move minus what the star would have drifted anyway.
        moves.append((step_ms, x1 - x0 - drift[0] * (t1 - t0), y1 - y0 - drift[1] * (t1 - t0)))
        x0, y0, t0 = x1, y1, t1
    sizes = [math.hypot(dx, dy) / ms for ms, dx, dy in moves]
    typical = float(np.median(sizes[1:] if len(sizes) > 2 else sizes))
    if typical <= 0:
        raise CalibrationFailed(f"the star did not move with {direction} pulses")
    # Slack (backlash) makes the first pulses move the star less than later ones.
    used = [i for i, size in enumerate(sizes) if size >= 0.8 * typical]
    if len(used) < 2:
        raise CalibrationFailed(f"too few usable {direction} steps")
    kept = [moves[i] for i in used]
    slack_ms = sum(moves[i][0] * (1 - sizes[i] / typical) for i in range(len(moves)) if i not in used)
    total_ms = sum(ms for ms, _, _ in kept)
    return (
        sum(dx for _, dx, _ in kept) / total_ms,
        sum(dy for _, _, dy in kept) / total_ms,
        float(slack_ms),
    )


async def calibrate(
    measure: Measure,
    pulse: Pulse,
    *,
    steps: int = 6,
    target_px: float = 3.0,
    max_ms: int = 4000,
    min_axis_angle_deg: float = 30.0,
    drift_samples: int = 5,
    clock: Callable[[], float] = time.monotonic,
) -> Calibration:
    """Pulse West then North, measuring the star after each pulse, and return the matrix.

    *measure* returns the star's sensor position once a frame taken after the last pulse is in.
    The star is pulsed back afterwards, but exactly where it ends up is irrelevant: the
    caller re-locks on it.
    """
    timed = _timed(measure, clock)
    drift = await _drift(timed, drift_samples)
    step_ms = await _probe(timed, pulse, "W", target_px=target_px, max_ms=max_ms, drift=drift)
    ra_x, ra_y, _ = await _sweep(timed, pulse, "W", steps, step_ms, drift)
    ra_speed = math.hypot(ra_x, ra_y)
    await _return(timed, pulse, "E", steps, step_ms)
    # Guide speed is the same on both axes for almost every mount: size Dec steps from RA's rate.
    dec_step = int(min(max(target_px / ra_speed, 50), max_ms))
    dec_x, dec_y, slack = await _sweep(timed, pulse, "N", steps + 2, dec_step, drift)
    await _return(timed, pulse, "S", steps + 2, dec_step)

    cal = Calibration(ra_x=ra_x, ra_y=ra_y, dec_x=dec_x, dec_y=dec_y, dec_backlash_ms=slack)
    cos = abs(ra_x * dec_x + ra_y * dec_y) / (cal.ra_rate * cal.dec_rate)
    if math.degrees(math.acos(min(cos, 1.0))) < min_axis_angle_deg:
        raise CalibrationFailed("RA and Dec moved the star along the same line")
    return cal
