"""Tests for the measurements the benchmark makes (not the run against a camera)."""
from __future__ import annotations

import numpy as np
import pytest

from astrolol.plugins.stacked_camera.benchmark import brightest, pair_noise, star_flux


def _sky(seed: int, sigma: float = 4.0, shape: tuple[int, int] = (200, 240)) -> np.ndarray:
    return 1000 + np.random.default_rng(seed).normal(0, sigma, shape)


def test_pair_noise_recovers_the_noise_of_one_frame() -> None:
    assert pair_noise(_sky(1), _sky(2)) == pytest.approx(4.0, rel=0.05)


def test_pair_noise_ignores_what_both_frames_share() -> None:
    pattern = np.random.default_rng(9).normal(0, 50, (200, 240))  # fixed pattern, bias, gradients
    assert pair_noise(_sky(1) + pattern, _sky(2) + pattern) == pytest.approx(4.0, rel=0.05)


def test_pair_noise_is_not_thrown_by_a_few_bright_stars() -> None:
    a, b = _sky(1), _sky(2)
    a[50:53, 60:63] += 3000  # a star that changed between the frames
    assert pair_noise(a, b) == pytest.approx(4.0, rel=0.05)


def test_brightest_finds_the_star_not_a_hot_pixel() -> None:
    frame = _sky(3, sigma=1.0)
    frame[120:125, 80:85] += 500  # a star: 25 pixels
    frame[10, 10] += 5000  # a hot pixel is brighter, but only one pixel
    row, col = brightest(frame)
    assert abs(row - 122) <= 2 and abs(col - 82) <= 2


def test_star_flux_is_the_light_above_the_background() -> None:
    frame = np.full((100, 100), 200.0)
    frame[48:53, 48:53] += 10.0  # 25 pixels, 10 ADU each
    assert star_flux(frame, (50, 50), half=5) == pytest.approx(250.0)


def test_star_flux_at_the_edge_of_the_frame() -> None:
    frame = np.full((50, 50), 100.0)
    frame[0:3, 0:3] += 4.0
    assert star_flux(frame, (1, 1), half=5) == pytest.approx(36.0)
