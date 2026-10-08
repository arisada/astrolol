"""Calibration: how guide pulses move the star on the sensor.

The result is a 2x2 matrix, not an angle and a rate per axis. Column 0 is the star's move
(pixels) per millisecond of West pulse, column 1 per millisecond of North pulse. That covers
any camera rotation, mirroring (a meridian flip, a diagonal) and slightly non-orthogonal axes
without special cases: a correction is the solution of ``M @ pulses = -error``.

Every measurement is kept (``Calibration.trace``) so the calibration can be inspected: the
points, which of them were used, and what the pulses did. The way back (East after West,
South after North) is measured the same way as the way out: it is a guaranteed reversal of
direction, which is exactly where gear slack shows, and it gives a second reading of the
speed.
"""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel

from astrolol.core.guiding.errors import GuiderError
from astrolol.devices.base.pulse import PulseDirection

Phase = Literal["drift", "probe", "west", "east", "north", "south"]


class CalibrationFailed(GuiderError):
    pass


class CalibrationPoint(BaseModel):
    phase: Phase
    step: int  # 0 is the position before the first pulse of the phase
    pulse_ms: int  # the pulse that preceded this measurement
    x: float  # sensor pixels
    y: float
    t: float  # seconds since calibration started
    used: bool = True  # False: measured, but left out of the fit (slack, probe, drift)


class Calibration(BaseModel):
    ra_x: float  # pixels per ms of West pulse (East is the opposite)
    ra_y: float
    dec_x: float  # pixels per ms of North pulse (South is the opposite)
    dec_y: float
    dec_backlash_ms: float = 0.0  # pulse time lost when Dec reverses
    ra_backlash_ms: float = 0.0  # same for RA (informational: RA corrections are not compensated)
    drift_x: float = 0.0  # pixels per second with no pulses
    drift_y: float = 0.0
    trace: list[CalibrationPoint] = []

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
Drift = tuple[float, float]  # pixels per second


@dataclass
class _Sweep:
    vx: float  # pixels per ms
    vy: float
    slack_ms: float
    points: list[CalibrationPoint]


class _Recorder:
    """Measures, and remembers every measurement with its time."""

    def __init__(self, measure: Measure, clock: Callable[[], float]) -> None:
        self._measure = measure
        self._clock = clock
        self._t0 = clock()

    async def __call__(self, phase: Phase, step: int, pulse_ms: int) -> CalibrationPoint:
        x, y = await self._measure()
        return CalibrationPoint(phase=phase, step=step, pulse_ms=pulse_ms, x=x, y=y, t=self._clock() - self._t0)


async def _drift(rec: _Recorder, samples: int) -> tuple[Drift, list[CalibrationPoint]]:
    """The star's drift with no pulses (a mount never tracks perfectly), by a straight-line fit."""
    pts = [await rec("drift", i, 0) for i in range(samples)]
    for p in pts:
        p.used = False
    t = np.array([p.t for p in pts]) - pts[0].t
    if t[-1] <= 0:
        return (0.0, 0.0), pts
    vx = float(np.polyfit(t, [p.x for p in pts], 1)[0])
    vy = float(np.polyfit(t, [p.y for p in pts], 1)[0])
    return (vx, vy), pts


async def _probe(
    rec: _Recorder, pulse: Pulse, direction: PulseDirection, *, target_px: float, max_ms: int, drift: Drift
) -> tuple[int, list[CalibrationPoint]]:
    """A pulse length that moves the star about *target_px*.

    Starts small: with a long focal length a one-second pulse can throw the star out of the
    window we track. The probe's own move is discarded (it also takes up any slack).
    """
    ms = 150
    points: list[CalibrationPoint] = []
    for _ in range(5):
        before = await rec("probe", 0, 0)
        await pulse(direction, ms)
        after = await rec("probe", 1, ms)
        before.used = after.used = False
        points += [before, after]
        dt = after.t - before.t
        moved = math.hypot(after.x - before.x - drift[0] * dt, after.y - before.y - drift[1] * dt)
        if moved >= 0.7:
            return int(min(max(ms * target_px / moved, 50), max_ms)), points
        ms = min(ms * 4, max_ms)
    raise CalibrationFailed(f"the star did not move with {direction} pulses")


async def _sweep(
    rec: _Recorder, pulse: Pulse, direction: PulseDirection, phase: Phase, steps: int, step_ms: int, drift: Drift
) -> _Sweep:
    """Pulse *steps* times, measuring after each; fit the speed from the steps that moved fully."""
    points = [await rec(phase, 0, 0)]
    moves: list[tuple[int, float, float]] = []  # (ms, dx, dy) of each pulse, drift removed
    for i in range(1, steps + 1):
        await pulse(direction, step_ms)
        p = await rec(phase, i, step_ms)
        prev = points[-1]
        dt = p.t - prev.t
        moves.append((step_ms, p.x - prev.x - drift[0] * dt, p.y - prev.y - drift[1] * dt))
        points.append(p)
    sizes = [math.hypot(dx, dy) / ms for ms, dx, dy in moves]
    typical = float(np.median(sizes[1:] if len(sizes) > 2 else sizes))
    if typical <= 0:
        raise CalibrationFailed(f"the star did not move with {direction} pulses")
    # Slack (backlash) makes the first pulses move the star less than later ones.
    used = [i for i, size in enumerate(sizes) if size >= 0.8 * typical]
    if len(used) < 2:
        raise CalibrationFailed(f"too few usable {direction} steps")
    for i in range(len(moves)):
        points[i + 1].used = i in used
    points[0].used = True  # the starting position anchors the picture
    kept = [moves[i] for i in used]
    slack_ms = sum(moves[i][0] * (1 - sizes[i] / typical) for i in range(len(moves)) if i not in used)
    total_ms = sum(ms for ms, _, _ in kept)
    return _Sweep(
        sum(dx for _, dx, _ in kept) / total_ms, sum(dy for _, _, dy in kept) / total_ms, float(slack_ms), points
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
    """Pulse West, East, North and South, measuring the star after each pulse.

    *measure* returns the star's sensor position once a frame taken after the last pulse is in.
    West then East (and North then South) bring the star back where it started, and the way
    back is analysed like the way out: it gives a second reading of the speed and, because the
    direction has just reversed, the backlash.
    """
    rec = _Recorder(measure, clock)
    trace: list[CalibrationPoint] = []

    drift, pts = await _drift(rec, drift_samples)
    trace += pts
    step_ms, pts = await _probe(rec, pulse, "W", target_px=target_px, max_ms=max_ms, drift=drift)
    trace += pts

    west = await _sweep(rec, pulse, "W", "west", steps, step_ms, drift)
    trace += west.points
    ra_x, ra_y, ra_backlash = west.vx, west.vy, 0.0
    try:
        east = await _sweep(rec, pulse, "E", "east", steps, step_ms, drift)
    except CalibrationFailed:
        pass  # the way back is a bonus; the way out stands
    else:
        trace += east.points
        ra_x, ra_y = (west.vx - east.vx) / 2, (west.vy - east.vy) / 2
        ra_backlash = east.slack_ms

    # Guide speed is the same on both axes for almost every mount: size Dec steps from RA's rate.
    dec_step = int(min(max(target_px / math.hypot(ra_x, ra_y), 50), max_ms))
    north = await _sweep(rec, pulse, "N", "north", steps + 2, dec_step, drift)
    trace += north.points
    dec_x, dec_y, dec_backlash = north.vx, north.vy, north.slack_ms
    try:
        south = await _sweep(rec, pulse, "S", "south", steps + 2, dec_step, drift)
    except CalibrationFailed:
        pass
    else:
        trace += south.points
        dec_x, dec_y = (north.vx - south.vx) / 2, (north.vy - south.vy) / 2
        dec_backlash = south.slack_ms  # a certain reversal; the start of the North sweep is not

    cal = Calibration(
        ra_x=ra_x, ra_y=ra_y, dec_x=dec_x, dec_y=dec_y,
        dec_backlash_ms=dec_backlash, ra_backlash_ms=ra_backlash,
        drift_x=drift[0], drift_y=drift[1], trace=trace,
    )
    cos = abs(ra_x * dec_x + ra_y * dec_y) / (cal.ra_rate * cal.dec_rate)
    if math.degrees(math.acos(min(cos, 1.0))) < min_axis_angle_deg:
        raise CalibrationFailed("RA and Dec moved the star along the same line")
    return cal
