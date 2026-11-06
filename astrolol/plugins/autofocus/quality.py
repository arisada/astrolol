"""How far a finished focus run can be trusted, and why not when it cannot.

A run is ``poor`` when one of these holds, and ``causes`` says which:

* ``edge``: the minimum is not bracketed: fewer than two good samples on one side of it, or
  the fitted minimum lies outside the swept range. The optimum is an extrapolation.
* ``flat``: the sharpness hardly changes over the sweep. There is no V to find a minimum
  in, usually because the stars are too faint for the blur to show.
* ``noisy``: the samples do not follow a V (no valid fit, or a poor R²).
* ``few_stars``: many steps found too few stars to measure, as with clouds or a low target.

The limits below are first estimates (no real-sky sweeps were available to tune them on).
"""
from __future__ import annotations

from astrolol.plugins.autofocus.models import Cause, CurveFit, FitMetrics, FocusDataPoint, FocusQuality

# Samples needed on each side of the minimum for it to count as bracketed.
MIN_BRACKET = 2
# Worst / best sharpness over the sweep: below this the curve is flat.
MIN_SPREAD = 1.3
# R² of the fit below which the samples are called noisy (fits under 0.6 are rejected outright).
MIN_R_SQUARED = 0.85
# Share of the steps that must have found stars, and the fewest usable samples.
MIN_VALID_FRACTION = 0.7
MIN_VALID_POINTS = 4


def usable(data_points: list[FocusDataPoint]) -> list[FocusDataPoint]:
    return [dp for dp in data_points if dp.fwhm > 0 and dp.star_count > 0]


def edge_direction(data_points: list[FocusDataPoint], fit: CurveFit | None) -> int:
    """+1 / -1 when the focus is clearly beyond the highest / lowest position swept, else 0.

    That is the case when the fitted optimum itself lies outside the swept range, or when there
    is no valid fit and the best measured sample has fewer than two samples beyond it on one
    side: the curve has no arm there to fit, and is still falling towards that end. With a fit,
    the same when fewer than two samples lie beyond its optimum on one side. A best
    sample well inside with no valid fit is noise or a flat curve, which more sweeps do not help.
    """
    valid = usable(data_points)
    if len(valid) < 3:
        return 0
    positions = [dp.position for dp in data_points]
    lo, hi = min(positions), max(positions)
    if fit is not None:
        if fit.optimal_position > hi:
            return 1
        if fit.optimal_position < lo:
            return -1
        below = sum(1 for dp in valid if dp.position < fit.optimal_position)
        above = sum(1 for dp in valid if dp.position > fit.optimal_position)
        if above < MIN_BRACKET <= below:
            return 1
        if below < MIN_BRACKET <= above and lo > 0:
            return -1
        return 0
    best = min(valid, key=lambda dp: dp.fwhm).position
    above = sum(1 for p in positions if p > best)
    below = sum(1 for p in positions if p < best)
    if above < MIN_BRACKET and above <= below:
        return 1
    if below < MIN_BRACKET and lo > 0:
        return -1
    return 0


def assess(data_points: list[FocusDataPoint], fit: CurveFit | None) -> FocusQuality:
    """Verdict and causes for the samples of a run and the curve fitted to them."""
    valid = usable(data_points)
    metrics = FitMetrics(valid_points=len(valid), sampled_points=len(data_points))
    causes: list[Cause] = []

    if len(valid) < MIN_VALID_POINTS or (
        data_points and len(valid) / len(data_points) < MIN_VALID_FRACTION
    ):
        causes.append("few_stars")
    if not valid:
        return FocusQuality(verdict="poor", causes=causes, metrics=metrics)

    values = [dp.fwhm for dp in valid]
    metrics.spread = max(values) / min(values)
    centre = fit.optimal_position if fit is not None else min(valid, key=lambda dp: dp.fwhm).position
    metrics.below = sum(1 for dp in valid if dp.position < centre)
    metrics.above = sum(1 for dp in valid if dp.position > centre)
    if fit is not None:
        metrics.r_squared = fit.r_squared

    at_zero = min(dp.position for dp in data_points) == 0
    lopsided = metrics.above < MIN_BRACKET or (metrics.below < MIN_BRACKET and not at_zero)
    if edge_direction(data_points, fit) != 0 or (len(valid) >= 3 and lopsided):
        causes.append("edge")
    elif metrics.spread < MIN_SPREAD:
        causes.append("flat")
    elif fit is None or (fit.r_squared is not None and fit.r_squared < MIN_R_SQUARED):
        causes.append("noisy")

    return FocusQuality(verdict="poor" if causes else "good", causes=causes, metrics=metrics)
