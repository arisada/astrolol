import numpy as np

from astrolol.plugins.polar_align.smoothing import OneEuroFilter


def test_a_still_star_loses_most_of_its_noise() -> None:
    rng = np.random.default_rng(0)
    f = OneEuroFilter()
    raw = 100.0 + rng.normal(0.0, 0.33, 200)
    out = np.array([f(x, float(i)) for i, x in enumerate(raw)])
    assert out[30:].std() < 0.45 * raw[30:].std()
    assert abs(out[30:].mean() - 100.0) < 0.1


def test_a_moving_star_is_followed_without_long_lag() -> None:
    f = OneEuroFilter()
    for i in range(10):
        f(100.0, float(i))
    # The knob is turned: 5 pixels per second for 10 s.
    out = [f(100.0 + 5.0 * i, 10.0 + i) for i in range(1, 11)]
    assert abs(out[-1] - 150.0) < 8.0  # lags by a few frames at most
    assert out[-1] > out[0]


def test_a_jump_is_followed_within_a_few_frames() -> None:
    f = OneEuroFilter()
    for i in range(10):
        f(0.0, float(i))
    out = [f(40.0, 10.0 + i) for i in range(8)]
    assert out[-1] > 30.0


def test_first_sample_passes_through_and_time_going_back_resets() -> None:
    f = OneEuroFilter()
    assert f(7.0, 5.0) == 7.0
    assert f(9.0, 1.0) == 9.0
