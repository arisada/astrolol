"""Focus curve fitting algorithms.

Two algorithms are supported:

Parabola (``parabola``)
    Fits  y = a·x² + b·x + c  to (position, FWHM) data.

Hyperbola (``hyperbola``)
    Fits  y² = a·x² + b·x + c  to (position, FWHM²) data, which is
    equivalent to the physical model  y = α·√((x−x₀)² + d²).
    The minimum is at x₀ = −b/(2a); the UI renders √(a·x²+b·x+c).

Both functions return  ``(a, b, c, optimal_position)``  so the CurveFit
model is unchanged, and the frontend selects the rendering formula based
on ``run.config.fit_algo``.
"""
from __future__ import annotations


def fit_parabola(
    positions: list[int],
    fwhms: list[float],
) -> tuple[float, float, float, float] | None:
    """Fit y = a·x² + b·x + c to (position, fwhm) data.

    Returns ``(a, b, c, optimal_position)`` or ``None`` when the fit is
    invalid (fewer than 3 points, downward parabola, or minimum outside
    the sampled range with 20 % margin).
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
            return None
        optimal = -b / (2.0 * a)
        x_min, x_max = float(x.min()), float(x.max())
        margin = (x_max - x_min) * 0.20
        if optimal < x_min - margin or optimal > x_max + margin:
            return None
        return a, b, c, optimal
    except Exception:
        return None


def fit_hyperbola(
    positions: list[int],
    fwhms: list[float],
) -> tuple[float, float, float, float] | None:
    """Fit y² = a·x² + b·x + c (i.e. y = √(a·x²+b·x+c)) to data.

    Fitting a parabola to the squared FWHM is the linearised form of the
    physical hyperbolic model  y = α·√((x−x₀)²+d²).  The optimal focus
    position is x₀ = −b/(2a); the minimum FWHM is √(c − b²/(4a)).

    Returns ``(a, b, c, optimal_position)`` or ``None`` when invalid.
    """
    if len(positions) < 3:
        return None
    try:
        import numpy as np
        x = np.array(positions, dtype=float)
        y2 = np.array(fwhms, dtype=float) ** 2
        coeffs = np.polyfit(x, y2, 2)
        a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])
        if a <= 0:
            return None
        optimal = -b / (2.0 * a)
        # Minimum of the fitted parabola in y² must be non-negative
        if c - b ** 2 / (4.0 * a) < 0:
            return None
        x_min, x_max = float(x.min()), float(x.max())
        margin = (x_max - x_min) * 0.20
        if optimal < x_min - margin or optimal > x_max + margin:
            return None
        return a, b, c, optimal
    except Exception:
        return None
