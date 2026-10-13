"""Predicts the star's own motion along one axis: a steady drift, and on RA the periodic error
of the worm gear.

The guider sees the star's own motion between two frames as the change of the error that the
pulses sent do not explain. ``MotionPredictor`` collects these as average rates over each
interval and fits rate(t) = c + sum_k (a_k cos(k w t) + b_k sin(k w t)), w = 2 pi / period,
each basis function averaged over its interval. The period is the mount's worm period when
given, else the one that best explains the recent history.

The periodic part is used only once the history covers two periods and the fit explains a
clear share of the motion beyond the drift: a wrong prediction costs more than none.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

HARMONICS = 2
MIN_PERIODS = 2.0  # history needed before the periodic part is trusted
# The fit must explain this many times the share of the variance that fitting pure noise
# with the same number of terms would (2 per harmonic over N samples), and at least 5%.
# Rates are noisy (a position error over a short interval), so a real periodic error can
# explain well under half of their variance and still be worth predicting.
SIGNIFICANCE = 6.0
MIN_EXPLAINED = 0.05
REFIT_EVERY = 10  # samples between fits...
REFIT_EVERY_S = 30.0  # ...and seconds: the period search costs, on a Pi, with fast frames
MAX_HISTORY_S = 3600.0
FULL_SEARCH_EVERY_S = 300.0  # at most, between searches over every period (else around the one found)
BIN_S = 4.0  # samples are merged into bins this long before fitting
RECENCY_PERIODS = 1.5  # time constant of the weight of older samples, in periods
DRIFT_ALPHA = 0.12


class MotionPredictor:
    def __init__(self, period_s: float | None = None, *, periodic: bool = True) -> None:
        self.period_s = period_s  # fixed (the mount's worm period), or None: found from the history
        self.periodic = periodic
        self._samples: deque[tuple[float, float, float]] = deque()  # (start, end, rate px/s)
        self.drift = 0.0  # px/s, a slow average: what is used while there is no periodic model
        self._n = 0
        self._since_fit = 0
        self._last_fit = self._last_search = float("-inf")
        self._coef: np.ndarray | None = None  # [c, a1, b1, a2, b2, ...]
        self.found_period: float | None = None
        self.explained = 0.0

    def reset(self) -> None:
        self._samples.clear()
        self.drift = 0.0
        self._n = self._since_fit = 0
        self._last_fit = self._last_search = float("-inf")
        self._coef = None
        self.found_period = None
        self.explained = 0.0

    @property
    def active_period(self) -> float | None:
        """The period of the periodic part in use, None while only the drift is predicted."""
        return self.found_period if self._coef is not None else None

    @property
    def amplitude_px(self) -> float:
        """Peak-to-peak amplitude of the periodic error in position, as modelled."""
        if self._coef is None or not self.found_period:
            return 0.0
        w = 2 * math.pi / self.found_period
        t = np.linspace(0, self.found_period, 200)
        pos = sum(
            (self._coef[2 * k - 1] * np.sin(k * w * t) - self._coef[2 * k] * np.cos(k * w * t)) / (k * w)
            for k in range(1, HARMONICS + 1)
        )
        return float(np.max(pos) - np.min(pos))

    def add(self, start: float, end: float, rate: float) -> None:
        """The star moved on its own at *rate* px/s on average between *start* and *end*."""
        if end <= start:
            return
        self._n += 1
        alpha = max(DRIFT_ALPHA, 1.0 / self._n)
        self.drift += alpha * (rate - self.drift)
        if not self.periodic:
            return
        self._samples.append((start, end, rate))
        while self._samples and end - self._samples[0][0] > MAX_HISTORY_S:
            self._samples.popleft()
        self._since_fit += 1
        span = end - self._samples[0][0]
        if self._since_fit >= REFIT_EVERY and end - self._last_fit >= min(REFIT_EVERY_S, span / 20):
            self._since_fit = 0
            self._last_fit = end
            self._fit()

    def displacement(self, start: float, end: float) -> float:
        """Predicted own motion (px) between *start* and *end*."""
        if self._n < 3:
            return 0.0
        if self._coef is None or not self.found_period:
            return self.drift * (end - start)
        row = _basis(np.array([start]), np.array([end]), self.found_period)[0]
        return float(row @ self._coef) * (end - start)

    def _binned(self) -> np.ndarray:
        """The samples merged into bins of at least BIN_S seconds (contiguous ones only): fast
        frames add samples, not information about a motion that takes minutes."""
        # Short against the shortest period worth looking for (a few hundredths of the history).
        span = self._samples[-1][1] - self._samples[0][0]
        size = min(BIN_S, span / 400)
        out: list[list[float]] = []
        for start, end, rate in self._samples:
            if out and end - out[-1][0] <= size and start - out[-1][1] < 1.0:
                b = out[-1]
                moved = b[2] * (b[1] - b[0]) + rate * (end - start)
                b[1] = end
                b[2] = moved / (b[1] - b[0])
            else:
                out.append([start, end, rate])
        return np.array(out)

    def _fit(self) -> None:
        s = self._binned()
        if len(s) < 20:
            return
        span = s[-1, 1] - s[0, 0]
        starts, ends, rates = s[:, 0], s[:, 1], s[:, 2]
        last = float(ends[-1])
        weights = ends - starts  # longer intervals average more noise out
        searched = False
        if self.period_s:
            periods = [self.period_s]
        elif self.found_period and last - self._last_search < min(FULL_SEARCH_EVERY_S, 2 * self.found_period):
            periods = list(np.linspace(self.found_period * 0.95, self.found_period * 1.05, 41))  # follow it
        else:
            periods = _candidates(float(np.median(weights)), span)
            self._last_search, searched = last, True
        def fit(period: float, recent: bool = False) -> tuple[float, float, np.ndarray]:
            # The period is looked for with every sample weighted alike. Its final coefficients
            # weight recent samples more: a period known only to a percent or two then still
            # gives the right phase where the prediction is used, at the end of the history.
            wt = weights * np.exp(-(last - ends) / (RECENCY_PERIODS * period)) if recent else weights
            mean = np.average(rates, weights=wt)
            var = float(np.average((rates - mean) ** 2, weights=wt))
            a = _basis(starts, ends, period)
            sw = np.sqrt(wt)
            coef, *_ = np.linalg.lstsq(a * sw[:, None], rates * sw, rcond=None)
            resid = float(np.average((rates - a @ coef) ** 2, weights=wt))
            return (1 - resid / var if var > 0 else 0.0), period, coef

        trials = [fit(period) for period in periods if span >= MIN_PERIODS * period]
        best: tuple[float, float, np.ndarray] | None = None
        if trials and searched:
            # Twice the period, with its second harmonic, explains the same motion: take the
            # shortest period that explains nearly as much as the best.
            top = max(t[0] for t in trials)
            best = min((t for t in trials if t[0] >= top - 0.03 * max(top, 0.0)), key=lambda t: t[1])
        elif trials:
            best = max(trials, key=lambda t: t[0])
        if best is not None and searched:  # refine around the best of the coarse grid
            for period in np.linspace(best[1] * 0.96, best[1] * 1.04, 41):
                if span >= MIN_PERIODS * period:
                    trial = fit(float(period))
                    if trial[0] > best[0]:
                        best = trial
        threshold = max(MIN_EXPLAINED, SIGNIFICANCE * 2 * HARMONICS / len(rates))
        if best is None or best[0] < threshold:
            self._coef, self.found_period, self.explained = None, None, best[0] if best else 0.0
            return
        self.explained, self.found_period = best[0], best[1]
        self._coef = fit(best[1], recent=True)[2]


def _basis(starts: np.ndarray, ends: np.ndarray, period: float) -> np.ndarray:
    """Each basis function averaged over [start, end]."""
    w = 2 * math.pi / period
    dt = ends - starts
    cols = [np.ones_like(starts)]
    for k in range(1, HARMONICS + 1):
        kw = k * w
        cols.append((np.sin(kw * ends) - np.sin(kw * starts)) / (kw * dt))
        cols.append(-(np.cos(kw * ends) - np.cos(kw * starts)) / (kw * dt))
    return np.column_stack(cols)


def _candidates(cycle: float, span: float) -> list[float]:
    """Periods worth trying: from a few guide cycles to half the history, geometrically spaced."""
    low = max(8 * cycle, 20.0 if cycle > 0.5 else 2.0)
    high = span / MIN_PERIODS
    if high <= low:
        return []
    n = int(min(120, max(10, 40 * math.log(high / low))))
    return list(np.geomspace(low, high, n))
