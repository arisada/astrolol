"""Focus curve fitting algorithms.

The V-curve (also called U-curve) method fits a parabola to (focuser_position,
median_FWHM) data points.  The minimum of the parabola is the estimated
optimal focus position.
"""
from __future__ import annotations


def fit_parabola(
    positions: list[int],
    fwhms: list[float],
) -> tuple[float, float, float, float] | None:
    """Fit y = a·x² + b·x + c to the (position, fwhm) data.

    Returns ``(a, b, c, optimal_position)`` or ``None`` when the fit is invalid.

    A fit is considered invalid when:
    - Fewer than 3 data points
    - The parabola opens downward (a ≤ 0) — not a proper focus minimum
    - The computed minimum lies outside the sampled range (with 20 % margin),
      which indicates noise or a bad sample set
    """
    if len(positions) < 3:
        return None

    try:
        import numpy as np

        x = np.array(positions, dtype=float)
        y = np.array(fwhms, dtype=float)

        coeffs = np.polyfit(x, y, 2)
        a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])

        if a <= 0:
            return None  # downward parabola — no valid minimum

        optimal = -b / (2.0 * a)

        x_min, x_max = float(x.min()), float(x.max())
        margin = (x_max - x_min) * 0.20
        if optimal < x_min - margin or optimal > x_max + margin:
            return None  # minimum outside sampled range

        return a, b, c, optimal

    except Exception:
        return None
