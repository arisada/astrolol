"""The star's own motion: drift, and the periodic error of an RA worm."""
import math

import numpy as np
import pytest

from astrolol.plugins.guider.calibration import Calibration
from astrolol.plugins.guider.controller import AxisSettings, GuideController
from astrolol.plugins.guider.predictor import MotionPredictor


def pe_rate(t: float, amp_px: float = 5.0, period: float = 480.0, drift: float = 0.02) -> float:
    """Rate (px/s) of a sinusoidal periodic error of *amp_px* amplitude, plus a drift."""
    w = 2 * math.pi / period
    return drift + amp_px * w * math.cos(w * t)


def feed(p: MotionPredictor, seconds: float, cycle: float = 4.0, noise_px: float = 0.3, seed: int = 0, **kw) -> None:  # noqa: ANN003
    rng = np.random.default_rng(seed)
    t = 0.0
    while t < seconds:
        mid = t + cycle / 2
        # A rate measured from two noisy positions: the noise is divided by the interval.
        rate = pe_rate(mid, **kw) + rng.normal(0, noise_px * math.sqrt(2) / cycle)
        p.add(t, t + cycle, rate)
        t += cycle


def test_the_worm_period_is_found_from_the_history() -> None:
    p = MotionPredictor()
    feed(p, 3 * 480)
    assert p.active_period == pytest.approx(480, rel=0.03)
    assert p.amplitude_px == pytest.approx(10, rel=0.15)  # peak to peak


def test_a_given_period_is_used() -> None:
    p = MotionPredictor(period_s=480)
    feed(p, 2.5 * 480)
    assert p.active_period == 480


def test_nothing_periodic_is_invented_from_noise() -> None:
    p = MotionPredictor()
    feed(p, 3 * 480, amp_px=0.0)
    assert p.active_period is None
    assert p.displacement(0, 4) == pytest.approx(0.02 * 4, abs=0.2)  # the drift alone (seeing: +-0.1 px)


def test_too_short_a_history_predicts_only_the_drift() -> None:
    p = MotionPredictor()
    feed(p, 1.5 * 480)
    assert p.active_period is None


def test_the_prediction_follows_the_error() -> None:
    p = MotionPredictor()
    feed(p, 3 * 480 + 100)
    t = 3 * 480 + 100  # the next interval, as when guiding
    w = 2 * math.pi / 480
    truth = 0.02 * 4 + 5.0 * (math.sin(w * (t + 4)) - math.sin(w * t))
    assert p.displacement(t, t + 4) == pytest.approx(truth, abs=0.04)


def _guided_rms(periodic: bool, minutes: float = 40, seed: int = 1) -> float:
    """A star with 15 px of periodic error over 480 s and 0.3 px of seeing, corrected every 4 s."""
    rng = np.random.default_rng(seed)
    cal = Calibration(ra_x=0.01, ra_y=0.0, dec_x=0.0, dec_y=0.01)
    c = GuideController(cal, AxisSettings(min_pulse_ms=5), AxisSettings(min_pulse_ms=5), predict_periodic=periodic)
    w = 2 * math.pi / 480
    corrected, errors = 0.0, []
    t = 0.0
    while t < minutes * 60:
        true = 15.0 * math.sin(w * t) + 0.02 * t + corrected
        seen = true + rng.normal(0, 0.3)
        if t > minutes * 60 / 2:
            errors.append(true)
        for d, ms in c.correct(seen, 0.0, now=t):
            corrected += {"W": 1, "E": -1}.get(d, 0) * ms * 0.01
        t += 4.0
    return float(np.sqrt(np.mean(np.square(errors))))


def test_predicting_the_periodic_error_beats_correcting_it_afterwards() -> None:
    plain = _guided_rms(False)
    predicted = _guided_rms(True)
    assert predicted < 0.6 * plain, (plain, predicted)


def test_a_period_too_long_for_the_history_is_not_guessed_short() -> None:
    # 650 s of a 480 s error: periods up to 325 s are searchable, and the best of them is a
    # wrong one at the edge of that range.
    p = MotionPredictor()
    rng = np.random.default_rng(3)
    t, at_650 = 0.0, "unset"
    while t < 3 * 480:
        p.add(t, t + 4, pe_rate(t + 2) + rng.normal(0, 0.1 * math.sqrt(2) / 4))
        t += 4
        if at_650 == "unset" and t >= 650:
            at_650 = p.active_period
    assert at_650 is None
    assert p.active_period == pytest.approx(480, rel=0.03)
