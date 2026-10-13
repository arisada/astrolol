"""Calibration: how guide pulses move the star on the sensor.

The result is a 2x2 matrix, not an angle and a rate per axis. Column 0 is the star's move
(pixels) per millisecond of West pulse, column 1 per millisecond of North pulse. That covers
any camera rotation, mirroring (a meridian flip, a diagonal) and slightly non-orthogonal axes
without special cases: a correction is the solution of ``M @ pulses = -error``.

The sequence:

1. *drift*: a few frames without pulses, for the noise of a measurement and a first drift.
2. *probe* West: pulses of growing length until the star moves clearly, twice in a row the
   same way (one move could be seeing). That gives the step length for the sweeps.
3. *west* then *east*: equal steps out and the same number back.
4. *probe* North: as for West, sized on its own (the RA speed shrinks with the cosine of the
   declination, Dec's does not). Its pulses also take up any slack in the Dec gears, so the
   North sweep starts with the gears engaged.
5. *north* then *south*.

All the points go into one least-squares fit: per coordinate, position = a start offset for
each phase + RA speed × West ms + Dec speed × North ms + drift × time. Fitting the drift with
the speeds (rather than from the first few frames alone) keeps a poor drift estimate from
leaking into the speeds. The first steps of a phase that moved the star much less than the
others are the gears' slack: they are left out, and their pulse time is the backlash.

Every measurement is kept (``Calibration.trace``), and also when calibration fails
(``CalibrationFailed.trace``), so it can be inspected.
"""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable, Callable
from typing import Literal

import numpy as np
from pydantic import BaseModel

from astrolol.core.guiding.errors import GuiderError
from astrolol.devices.base.pulse import PulseDirection

Phase = Literal["drift", "probe", "west", "east", "north", "south"]
SWEEPS: tuple[Phase, ...] = ("west", "east", "north", "south")
_DIRECTION: dict[Phase, PulseDirection] = {"west": "W", "east": "E", "north": "N", "south": "S"}

MAX_DEC_COMPENSATION_DEG = 75.0  # past this the RA speed is too small to scale reliably


class CalibrationPoint(BaseModel):
    phase: Phase
    step: int  # 0 is the position before the first pulse of the phase
    pulse_ms: int  # the pulse that preceded this measurement
    x: float  # sensor pixels
    y: float
    t: float  # seconds since calibration started
    used: bool = True  # False: measured, but left out of the fit (slack, probe)


class CalibrationQuality(BaseModel):
    """How far to trust a calibration. ``issues`` holds codes the UI words for the user."""

    residual_px: float = 0.0  # RMS distance of the points from the fit
    noise_px: float = 0.0  # scatter of the star's position between frames, without pulses
    ra_travel_px: float = 0.0  # how far the West sweep moved the star
    dec_travel_px: float = 0.0
    axes_angle_deg: float = 90.0  # angle between the RA and Dec directions on the sensor
    ra_asymmetry: float | None = None  # |West speed - East speed| / mean
    dec_asymmetry: float | None = None
    rate_ratio: float = 1.0  # RA speed / Dec speed
    expected_ratio: float | None = None  # cos(declination), when the declination is known
    issues: list[str] = []


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
    # Where and with what it was made, to adjust it to another pointing and to know when it
    # no longer applies.
    dec: float | None = None  # degrees
    pier_side: str | None = None
    camera_id: str | None = None
    mount_id: str | None = None
    guide_output: str | None = None
    created: float | None = None  # Unix time
    quality: CalibrationQuality | None = None

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

    def for_pointing(self, dec: float | None, pier_side: str | None, *, flip_dec: bool) -> Calibration:
        """This calibration as it applies at another declination and pier side.

        The RA speed on the sky scales with the cosine of the declination. After a meridian
        flip the camera has turned half a turn with the tube, so West moves the star the other
        way on the sensor; North does too when the mount's North follows the sky (*flip_dec*),
        not when it drives the motor one fixed way.
        """
        ra_x, ra_y, dec_x, dec_y = self.ra_x, self.ra_y, self.dec_x, self.dec_y
        if dec is not None and self.dec is not None:
            limit = math.cos(math.radians(MAX_DEC_COMPENSATION_DEG))
            factor = max(math.cos(math.radians(dec)), limit) / max(math.cos(math.radians(self.dec)), limit)
            ra_x, ra_y = ra_x * factor, ra_y * factor
        if pier_side and self.pier_side and pier_side != self.pier_side:
            ra_x, ra_y = -ra_x, -ra_y
            if flip_dec:
                dec_x, dec_y = -dec_x, -dec_y
        if (ra_x, ra_y, dec_x, dec_y) == (self.ra_x, self.ra_y, self.dec_x, self.dec_y) and (
            dec == self.dec or dec is None
        ):
            return self
        return self.model_copy(
            update={"ra_x": ra_x, "ra_y": ra_y, "dec_x": dec_x, "dec_y": dec_y, "dec": dec, "pier_side": pier_side or self.pier_side}
        )

    def with_dec_reversed(self) -> Calibration:
        return self.model_copy(update={"dec_x": -self.dec_x, "dec_y": -self.dec_y})

    def with_ra_reversed(self) -> Calibration:
        return self.model_copy(update={"ra_x": -self.ra_x, "ra_y": -self.ra_y})


class CalibrationFailed(GuiderError):
    def __init__(self, message: str, trace: list[CalibrationPoint] | None = None) -> None:
        super().__init__(message)
        self.trace = trace or []


Measure = Callable[[], Awaitable[tuple[float, float]]]
Pulse = Callable[[PulseDirection, int], Awaitable[None]]
Progress = Callable[[list[CalibrationPoint], str], None]


class _Recorder:
    """Measures, and remembers every measurement with its time."""

    def __init__(self, measure: Measure, clock: Callable[[], float], progress: Progress | None) -> None:
        self._measure = measure
        self._clock = clock
        self._t0 = clock()
        self._progress = progress
        self.trace: list[CalibrationPoint] = []

    async def __call__(self, phase: Phase, step: int, pulse_ms: int) -> CalibrationPoint:
        x, y = await self._measure()
        p = CalibrationPoint(phase=phase, step=step, pulse_ms=pulse_ms, x=x, y=y, t=self._clock() - self._t0)
        self.trace.append(p)
        if self._progress is not None:
            self._progress(self.trace, phase)
        return p


def _drift_fit(pts: list[CalibrationPoint]) -> tuple[tuple[float, float], float]:
    """(drift px/s, noise px) from points taken without pulses."""
    t = np.array([p.t for p in pts])
    xs, ys = np.array([p.x for p in pts]), np.array([p.y for p in pts])
    if len(pts) < 3 or t[-1] - t[0] <= 0:
        return (0.0, 0.0), 0.0
    cx, cy = np.polyfit(t, xs, 1), np.polyfit(t, ys, 1)
    rx, ry = xs - np.polyval(cx, t), ys - np.polyval(cy, t)
    noise = float(np.sqrt((np.sum(rx**2) + np.sum(ry**2)) / max(len(pts) - 2, 1)))
    return (float(cx[0]), float(cy[0])), noise


def _moved(a: CalibrationPoint, b: CalibrationPoint, drift: tuple[float, float]) -> np.ndarray:
    dt = b.t - a.t
    return np.array([b.x - a.x - drift[0] * dt, b.y - a.y - drift[1] * dt])


async def _probe(
    rec: _Recorder, pulse: Pulse, direction: PulseDirection, *,
    step_px: float, max_ms: int, drift: tuple[float, float], noise: float, start_ms: int = 100,
) -> tuple[int, np.ndarray]:
    """A pulse length that moves the star about *step_px*, and the move seen (px per ms).

    The pulse grows until the star moves clearly (well beyond the frame-to-frame noise) twice
    in a row in the same direction. Starts small: with a long focal length a one-second pulse
    can throw the star out of the window we track. Its moves stay out of the fit; on Dec they
    also take up the gears' slack.
    """
    clear = max(0.8, 4.0 * noise)
    ms = start_ms
    at_max = 0
    step = 0
    last = await rec("probe", step, 0)
    last.used = False
    for _ in range(12):
        await pulse(direction, ms)
        step += 1
        first = await rec("probe", step, ms)
        first.used = False
        m1 = _moved(last, first, drift)
        last = first
        if np.hypot(*m1) >= clear:
            await pulse(direction, ms)
            step += 1
            second = await rec("probe", step, ms)
            second.used = False
            m2 = _moved(first, second, drift)
            last = second
            n1, n2 = float(np.hypot(*m1)), float(np.hypot(*m2))
            if n2 >= 0.5 * n1 and float(np.dot(m1, m2)) / (n1 * n2) > math.cos(math.radians(40)):
                rate = (n1 + n2) / (2 * ms)
                return int(min(max(step_px / rate, 20), max_ms)), (m1 + m2) / (2 * ms)
            # One move and then not the next: seeing or slack. Try again at the same length.
            continue
        if ms >= max_ms:
            at_max += 1
            if at_max >= 2:
                break
        ms = int(min(ms * 2, max_ms))
    raise CalibrationFailed(f"the star did not move with {direction} pulses", rec.trace)


async def _sweep(
    rec: _Recorder, pulse: Pulse, phase: Phase, step_ms: int, *,
    steps: int, travel_px: float | None, drift: tuple[float, float],
) -> int:
    """Pulse in *phase*'s direction, measuring after each pulse; returns the pulses sent.

    With *travel_px*, goes on past *steps* (up to twice as many) until the star has moved
    at least 60% of it: the probe can overestimate the speed.
    """
    direction = _DIRECTION[phase]
    start = await rec(phase, 0, 0)
    n = 0
    while True:
        await pulse(direction, step_ms)
        n += 1
        p = await rec(phase, n, step_ms)
        if n >= 2 * steps:
            break
        if n >= steps:
            moved = float(np.hypot(*_moved(start, p, drift)))
            if travel_px is None or moved >= 0.6 * travel_px:
                break
    return n


def _segment(trace: list[CalibrationPoint], phase: Phase) -> list[CalibrationPoint]:
    return [p for p in trace if p.phase == phase]


def _mark_slack(pts: list[CalibrationPoint], drift: tuple[float, float], expected: np.ndarray) -> bool:
    """Leave out the first steps of a sweep that moved much less than the rest (gear slack).

    *expected* is the move of one step as the probe saw it. Only leading steps count: a short
    step in the middle of a sweep is noise, and the fit absorbs it. Returns True when the
    whole sweep was slack (the star never moved as it should): it is then left out entirely.
    """
    if len(pts) < 2:
        return False
    size = float(np.hypot(*expected))
    u = expected / size
    proj = [float(np.dot(_moved(a, b, drift), u)) for a, b in zip(pts, pts[1:])]
    typical = float(np.median(proj[len(proj) // 2:]))
    if typical < 0.3 * size:
        for p in pts:
            p.used = False
        return True
    for i, step in enumerate(proj[:-2]):  # always keep at least two steps
        if step >= 0.7 * typical:
            break
        pts[i].used = False  # the point before a step that did not move is not on the line
    return False


def _fit(trace: list[CalibrationPoint]) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray, list[CalibrationPoint]]:
    """Least squares over the drift and sweep points marked used.

    Returns (coefficients 2 x columns, residuals per point, the column names, the design
    matrix, the points fitted).
    """
    pts = [p for p in trace if p.phase in ("drift", *SWEEPS) and p.used]
    phases = [ph for ph in ("drift", *SWEEPS) if any(p.phase == ph for p in pts)]
    rows = []
    for p in pts:
        seg = _segment(trace, p.phase)
        ms = sum(q.pulse_ms for q in seg if q.step <= p.step)
        cw = ms if p.phase == "west" else -ms if p.phase == "east" else 0
        cn = ms if p.phase == "north" else -ms if p.phase == "south" else 0
        rows.append([1.0 if p.phase == ph else 0.0 for ph in phases] + [cw, cn, p.t])
    a = np.array(rows, dtype=float)
    b = np.array([[p.x, p.y] for p in pts], dtype=float)
    coef, *_ = np.linalg.lstsq(a, b, rcond=None)
    residuals = b - a @ coef
    return coef.T, residuals, [*phases, "ra", "dec", "t"], a, pts


def _slack_ms(trace: list[CalibrationPoint], phase: Phase, coef: np.ndarray, cols: list[str], speed: np.ndarray) -> float:
    """Pulse time at the start of *phase* that did not move the star: where the fitted line
    reaches the phase's starting position."""
    seg = _segment(trace, phase)
    if not seg or phase not in cols:
        return 0.0
    start = seg[0]
    i = cols.index(phase)
    line0 = coef[:, i] + coef[:, cols.index("t")] * start.t  # the line at zero pulse time
    sign = 1.0 if phase in ("west", "north") else -1.0
    v = sign * speed
    vv = float(np.dot(v, v))
    if vv == 0:
        return 0.0
    return max(0.0, float(np.dot(np.array([start.x, start.y]) - line0, v)) / vv)


def _sweep_speed(trace: list[CalibrationPoint], phase: Phase, drift: np.ndarray) -> float | None:
    """Speed (px per ms) of one sweep alone, drift removed, slack left out."""
    pts = [p for p in _segment(trace, phase) if p.used]
    if len(pts) < 2:
        return None
    seg = _segment(trace, phase)
    cum = np.array([sum(q.pulse_ms for q in seg if q.step <= p.step) for p in pts], dtype=float)
    pos = np.array([[p.x - drift[0] * p.t, p.y - drift[1] * p.t] for p in pts])
    if cum[-1] == cum[0]:
        return None
    sx = np.polyfit(cum, pos[:, 0], 1)[0]
    sy = np.polyfit(cum, pos[:, 1], 1)[0]
    return float(np.hypot(sx, sy))


def _travel(trace: list[CalibrationPoint], phase: Phase) -> float:
    seg = _segment(trace, phase)
    return float(np.hypot(seg[-1].x - seg[0].x, seg[-1].y - seg[0].y)) if len(seg) > 1 else 0.0


def _slack_from_travel(trace: list[CalibrationPoint], phase: Phase, drift: np.ndarray, speed: np.ndarray) -> float:
    """Slack of a sweep that hardly moved: its pulse time less what the move it made took."""
    seg = _segment(trace, phase)
    total = float(sum(p.pulse_ms for p in seg))
    rate = float(np.hypot(*speed))
    if len(seg) < 2 or rate == 0:
        return total
    moved = float(np.dot(_moved(seg[0], seg[-1], (float(drift[0]), float(drift[1]))), -speed / rate))
    return max(0.0, total - max(moved, 0.0) / rate)


def _asymmetry(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or a + b == 0:
        return None
    return abs(a - b) / ((a + b) / 2)


async def calibrate(
    measure: Measure,
    pulse: Pulse,
    *,
    steps: int = 6,
    travel_px: float = 25.0,
    max_ms: int = 4000,
    min_axis_angle_deg: float = 30.0,
    drift_samples: int = 5,
    dec: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    progress: Progress | None = None,
) -> Calibration:
    """Pulse West, East, North and South, measuring the star after each pulse.

    *measure* returns the star's sensor position once a frame taken after the last pulse is in.
    *dec* (degrees), when known, is used to check the RA speed against the Dec speed.
    *progress* is called with the trace so far after every measurement.
    """
    rec = _Recorder(measure, clock, progress)
    try:
        return await _calibrate(rec, pulse, steps, travel_px, max_ms, min_axis_angle_deg, drift_samples, dec)
    except CalibrationFailed as exc:
        exc.trace = rec.trace
        raise
    except GuiderError as exc:
        raise CalibrationFailed(str(exc), rec.trace) from exc


async def _calibrate(
    rec: _Recorder, pulse: Pulse, steps: int, travel_px: float, max_ms: int,
    min_axis_angle_deg: float, drift_samples: int, dec: float | None,
) -> Calibration:
    drift_pts = [await rec("drift", i, 0) for i in range(drift_samples)]
    drift, noise = _drift_fit(drift_pts)
    step_px = travel_px / steps

    ra_ms, ra_move = await _probe(rec, pulse, "W", step_px=step_px, max_ms=max_ms, drift=drift, noise=noise)
    n = await _sweep(rec, pulse, "west", ra_ms, steps=steps, travel_px=travel_px, drift=drift)
    # The way back goes on (up to twice as many steps) until it has come most of the way:
    # the slack of the reversal is not known in advance.
    await _sweep(rec, pulse, "east", ra_ms, steps=n, travel_px=_travel(rec.trace, "west"), drift=drift)

    dec_ms, dec_move = await _probe(rec, pulse, "N", step_px=step_px, max_ms=max_ms, drift=drift, noise=noise)
    n = await _sweep(rec, pulse, "north", dec_ms, steps=steps, travel_px=travel_px, drift=drift)
    await _sweep(rec, pulse, "south", dec_ms, steps=n, travel_px=_travel(rec.trace, "north"), drift=drift)

    trace = rec.trace
    expected = {
        "west": ra_move * ra_ms, "east": -ra_move * ra_ms, "north": dec_move * dec_ms, "south": -dec_move * dec_ms,
    }
    all_slack = {phase: _mark_slack(_segment(trace, phase), drift, expected[phase]) for phase in SWEEPS}
    if all_slack["west"] or all_slack["north"]:
        raise CalibrationFailed(
            f"the star stopped moving with {'W' if all_slack['west'] else 'N'} pulses after the first ones", trace
        )

    coef, residuals, cols, _, fitted = _fit(trace)
    ra = coef[:, cols.index("ra")]
    dc = coef[:, cols.index("dec")]
    fitted_drift = coef[:, cols.index("t")]
    residual = float(np.sqrt(np.mean(np.sum(residuals**2, axis=1)))) if len(fitted) else 0.0

    ra_rate, dec_rate = float(np.hypot(*ra)), float(np.hypot(*dc))
    if ra_rate == 0 or dec_rate == 0:
        raise CalibrationFailed("the star did not move with the pulses", trace)
    cos = abs(float(np.dot(ra, dc))) / (ra_rate * dec_rate)
    angle = math.degrees(math.acos(min(cos, 1.0)))
    if angle < min_axis_angle_deg:
        raise CalibrationFailed("RA and Dec moved the star along the same line", trace)

    ra_travel, dec_travel = _travel(trace, "west"), _travel(trace, "north")
    issues: list[str] = []
    if residual > 0.25 * min(ra_travel, dec_travel):
        raise CalibrationFailed(
            f"the star's moves did not follow the pulses (scatter {residual:.1f} px over {min(ra_travel, dec_travel):.1f} px)",
            trace,
        )
    if residual > 0.08 * min(ra_travel, dec_travel):
        issues.append("noisy")
    if min(ra_travel, dec_travel) < 8:
        issues.append("short_travel")
    if abs(angle - 90) > 10:  # acos of |cos| lies in [0, 90]: 90 is perpendicular
        issues.append("not_perpendicular")
    if all_slack["south"]:
        issues.append("dec_backlash_large")  # most of the way back was slack
    if all_slack["east"]:
        issues.append("ra_backlash_large")
    ra_asym = _asymmetry(_sweep_speed(trace, "west", fitted_drift), _sweep_speed(trace, "east", fitted_drift))
    dec_asym = _asymmetry(_sweep_speed(trace, "north", fitted_drift), _sweep_speed(trace, "south", fitted_drift))
    if ra_asym is not None and ra_asym > 0.3:
        issues.append("ra_asymmetric")
    if dec_asym is not None and dec_asym > 0.3:
        issues.append("dec_asymmetric")
    ratio = ra_rate / dec_rate
    expected = None
    if dec is not None:
        expected = max(math.cos(math.radians(dec)), 0.0)
        if abs(dec) > MAX_DEC_COMPENSATION_DEG:
            issues.append("high_dec")
        elif expected > 0 and abs(ratio / expected - 1) > 0.3:
            issues.append("rate_ratio")

    return Calibration(
        ra_x=float(ra[0]), ra_y=float(ra[1]), dec_x=float(dc[0]), dec_y=float(dc[1]),
        dec_backlash_ms=_slack_ms(trace, "south", coef, cols, dc) if not all_slack["south"] else _slack_from_travel(trace, "south", fitted_drift, dc),
        ra_backlash_ms=_slack_ms(trace, "east", coef, cols, ra) if not all_slack["east"] else _slack_from_travel(trace, "east", fitted_drift, ra),
        drift_x=float(fitted_drift[0]), drift_y=float(fitted_drift[1]),
        trace=trace, dec=dec,
        quality=CalibrationQuality(
            residual_px=residual, noise_px=noise, ra_travel_px=ra_travel, dec_travel_px=dec_travel,
            axes_angle_deg=angle, ra_asymmetry=ra_asym, dec_asymmetry=dec_asym,
            rate_ratio=ratio, expected_ratio=expected, issues=issues,
        ),
    )
