"""quality.assess(): why a focus result should or should not be trusted."""
from __future__ import annotations

import pytest

from astrolol.plugins.autofocus.models import CurveFit, FocusDataPoint
from astrolol.plugins.autofocus.quality import assess


def _points(values: list[float], start: int = 750, step: int = 50, stars: int = 20) -> list[FocusDataPoint]:
    return [
        FocusDataPoint(step=i + 1, position=start + i * step, fwhm=v, star_count=0 if v <= 0 else stars)
        for i, v in enumerate(values)
    ]


def _fit(optimal: float, r_squared: float | None = 0.99) -> CurveFit:
    return CurveFit(a=1.0, b=0.0, c=0.0, optimal_position=optimal, r_squared=r_squared)


V = [4.0, 3.0, 2.2, 2.0, 2.3, 3.1, 4.2]      # 750 … 1050, minimum at 900


def test_a_bracketed_minimum_with_a_good_fit_is_good() -> None:
    q = assess(_points(V), _fit(905.0))
    assert (q.verdict, q.causes) == ("good", [])
    assert (q.metrics.below, q.metrics.above, q.metrics.valid_points) == (4, 3, 7)
    assert q.metrics.r_squared == 0.99
    assert q.metrics.spread == pytest.approx(2.1)


def test_an_optimum_outside_the_sweep_is_an_edge() -> None:
    assert assess(_points(V), _fit(1120.0)).causes == ["edge"]


def test_a_minimum_with_one_sample_beyond_it_is_an_edge_even_with_a_fit() -> None:
    """Valid fit, optimum inside the range, but a single sample past it: an extrapolation."""
    values = [6.0, 5.0, 4.0, 3.2, 2.6, 2.0, 2.5]      # best at 1000, one sample at 1050
    q = assess(_points(values), _fit(1010.0))
    assert q.causes == ["edge"]
    assert q.metrics.above == 1


def test_no_arm_below_is_not_an_edge_at_position_zero() -> None:
    values = [2.0, 2.5, 3.0, 3.6, 4.4, 5.2, 6.0]      # best at 0: cannot go lower
    q = assess(_points(values, start=0), _fit(10.0))
    assert "edge" not in q.causes


def test_a_curve_that_hardly_changes_is_flat() -> None:
    q = assess(_points([2.0, 2.05, 2.1, 2.0, 2.08, 2.1, 2.02]), _fit(900.0))
    assert q.causes == ["flat"]
    assert q.verdict == "poor"


def test_samples_that_do_not_form_a_v_are_noisy() -> None:
    noisy = [3.0, 2.6, 4.0, 2.0, 5.0, 3.0, 4.0]
    assert assess(_points(noisy), None).causes == ["noisy"]
    assert assess(_points(V), _fit(905.0, r_squared=0.7)).causes == ["noisy"]


def test_steps_without_stars_are_few_stars() -> None:
    values = [4.0, 0.0, 2.2, 2.0, 0.0, 0.0, 4.2]
    q = assess(_points(values), None)
    assert "few_stars" in q.causes
    assert q.metrics.valid_points == 4 and q.metrics.sampled_points == 7


def test_nothing_measured_is_few_stars_and_poor() -> None:
    q = assess(_points([0.0] * 7), None)
    assert (q.verdict, q.causes) == ("poor", ["few_stars"])
    assert q.metrics.spread is None


def test_no_samples_at_all_does_not_crash() -> None:
    assert assess([], None).verdict == "poor"


def test_a_check_frame_is_a_mismatch_when_clearly_less_sharp_or_empty() -> None:
    from astrolol.plugins.autofocus.quality import mismatched

    assert not mismatched(2.2, 2.0)
    assert not mismatched(1.8, 2.0)
    assert mismatched(2.6, 2.0)
    assert mismatched(None, 2.0) and mismatched(0.0, 2.0)


def test_the_fitted_minimum_of_a_parabola_and_a_hyperbola() -> None:
    from astrolol.plugins.autofocus.algorithms import fit_hyperbola, fit_minimum, fit_parabola

    positions = list(range(700, 1101, 50))
    parabola = [2.0 + 0.0004 * (p - 900) ** 2 for p in positions]
    a, b, c, _ = fit_parabola(positions, parabola)
    assert fit_minimum("parabola", a, b, c) == pytest.approx(2.0, abs=0.01)
    hyper = [(2.0 ** 2 + 0.0004 * (p - 900) ** 2) ** 0.5 for p in positions]
    a, b, c, _ = fit_hyperbola(positions, hyper)
    assert fit_minimum("hyperbola", a, b, c) == pytest.approx(2.0, abs=0.01)
