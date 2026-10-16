"""Smoothing for the star position that follows slow noise but not real motion."""
from __future__ import annotations

import math


class OneEuroFilter:
    """The "1 euro" filter (Casiez et al.): an exponential average whose cutoff rises with the
    speed of the signal. A star that sits still is averaged heavily, so the centroid noise of a
    faint star disappears; a star that moves because a knob is turned passes with little lag.

    *min_cutoff* (Hz) is the smoothing at rest, *beta* how quickly the cutoff opens with speed
    (Hz per unit/s), *d_cutoff* the smoothing of the speed estimate itself.
    """

    def __init__(self, min_cutoff: float = 0.05, beta: float = 0.05, d_cutoff: float = 0.3) -> None:
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self._t: float | None = None
        self._x = 0.0
        self._dx = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self) -> None:
        self._t = None

    def __call__(self, x: float, t: float) -> float:
        """The smoothed value for sample *x* taken at time *t* (seconds, increasing)."""
        if self._t is None or t <= self._t:
            self._t, self._x, self._dx = t, x, 0.0
            return x
        dt = t - self._t
        raw_speed = (x - self._x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx += a_d * (raw_speed - self._dx)
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        a = self._alpha(cutoff, dt)
        self._x += a * (x - self._x)
        self._t = t
        return self._x
