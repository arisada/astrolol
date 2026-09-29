"""_compute_hfd(): regression test for the bisection-on-noisy-data bug.

Background-subtracted data has negative noise pixels. Summing them into a
growing aperture makes the curve-of-growth non-monotonic, which breaks the
bisection search (it assumes flux(r) only increases with r) and used to send
the result to either extreme (near the 0.5px floor or near max_radius) on an
unlucky noise draw, instead of the true half-flux radius.
"""
from __future__ import annotations

import numpy as np
import pytest

from plugins.autofocus.star_detector import (
    _compute_hfd,
    _match_reference_stars,
    _sigma_clip_mask,
    _subsample_factor,
)

# For a 2D Gaussian PSF with std sigma, the analytic HFD equals the FWHM:
# encircled energy fraction at radius r is 1 - exp(-r^2 / (2 sigma^2)); solving
# for 50% gives r_half = sigma * sqrt(2 ln 2), so HFD = 2 r_half = 2.3548 sigma.
_SIGMA = 2.0
_EXPECTED_HFD = 2.3548 * _SIGMA


def _synthetic_star(rng: np.random.Generator, noise_std: float = 8.0) -> np.ndarray:
    size = 41
    cy = cx = size // 2
    yy, xx = np.mgrid[0:size, 0:size]
    amplitude = 400.0
    star = amplitude * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * _SIGMA ** 2))
    noise = rng.normal(0.0, noise_std, size=(size, size))  # zero-mean -> negative pixels
    return star + noise, cx, cy


@pytest.mark.parametrize("seed", range(15))
def test_compute_hfd_is_stable_under_background_noise(seed: int) -> None:
    rng = np.random.default_rng(seed)
    data, cx, cy = _synthetic_star(rng)
    hfd = _compute_hfd(data, float(cx), float(cy), max_radius=20.0)
    # A bisection corrupted by non-monotonic noise lands near the 0.5px floor
    # (diameter ~1.0) or near max_radius (diameter ~40) on an unlucky draw;
    # a correct measurement stays close to the analytic value across all seeds.
    assert abs(hfd - _EXPECTED_HFD) < 2.0, f"seed={seed} hfd={hfd} expected~{_EXPECTED_HFD}"


@pytest.mark.parametrize("seed", range(10))
def test_compute_hfd_is_not_biased_by_imperfect_background_subtraction(seed: int) -> None:
    """Regression: clipping negative background pixels to 0 (an earlier fix for the
    test above) rectifies the noise, giving it a small positive mean that grows with
    the aperture's area (~r^2) as the radius sweeps out — systematically inflating
    the result well past the analytic HFD, worse for a larger max_radius or a
    residual background offset (e.g. from an imperfect global sky estimate)."""
    rng = np.random.default_rng(seed)
    data, cx, cy = _synthetic_star(rng)
    data = data + 3.0  # residual background offset, as if global subtraction slightly missed
    hfd = _compute_hfd(data, float(cx), float(cy), max_radius=20.0)
    assert abs(hfd - _EXPECTED_HFD) < 3.0, f"seed={seed} hfd={hfd} expected~{_EXPECTED_HFD}"


# ── _subsample_factor(): detection-stage stride must scale with frame size ─────

def test_subsample_factor_applies_on_a_large_native_frame() -> None:
    assert _subsample_factor((1024, 1280)) == 2  # e.g. bin1 on a 1280x1024 sensor


def test_subsample_factor_is_a_noop_on_an_already_binned_frame() -> None:
    """Regression: a fixed stride applied unconditionally compounds with camera
    binning — a bin2 frame is already 1/4 the pixel count of bin1, so subsampling
    it again left only 1/16 of the sensor's original points feeding star centroid
    and FWHM estimates, hurting HFD (built from that centroid) more than FWHM."""
    assert _subsample_factor((512, 640)) == 1  # e.g. bin2 of the same sensor


# ── _sigma_clip_mask(): shared outlier rejection for FWHM and HFD medians ──────

def test_sigma_clip_mask_drops_a_lone_spike() -> None:
    """Regression: HFD used to skip this clip entirely (unlike FWHM), so one star's
    noise-driven bad reading (e.g. from a too-large aperture on a noisy background)
    could drag the whole step's median HFD."""
    values = np.array([2.1, 2.4, 2.0, 2.3, 13.0, 2.2, 2.5])
    mask = _sigma_clip_mask(values)
    assert mask[4] == False  # noqa: E712 — the 13.0 spike
    assert mask.sum() == 6


def test_sigma_clip_mask_keeps_everything_when_too_few_would_survive() -> None:
    """A handful of genuinely close values shouldn't be treated as all-outliers."""
    values = np.array([2.0, 2.1, 8.0])
    assert _sigma_clip_mask(values).all()


def test_sigma_clip_mask_keeps_everything_for_zero_spread() -> None:
    values = np.array([2.0, 2.0, 2.0])
    assert _sigma_clip_mask(values).all()


# ── _match_reference_stars(): the "lock_stars" preferred-population filter ─────

def _star(x: float, y: float, fwhm: float = 2.5) -> dict:
    return {"x": x, "y": y, "fwhm": fwhm}


def test_match_reference_stars_pairs_nearby_detections() -> None:
    reference = [_star(10, 10), _star(100, 100), _star(200, 200)]
    # This frame's detections: one moved slightly, one unchanged, one new star
    # with no reference counterpart (should be ignored, not matched).
    detected = [_star(101, 99, fwhm=3.0), _star(200, 201, fwhm=2.0), _star(500, 500)]

    matched = _match_reference_stars(detected, reference)

    assert len(matched) == 2
    assert {(round(s["x"]), round(s["y"])) for s in matched} == {(101, 99), (200, 201)}


def test_match_reference_stars_drops_a_reference_with_no_nearby_detection() -> None:
    """A star that spreads below the detection floor once defocused is simply
    skipped for that step — not treated as an error."""
    reference = [_star(10, 10), _star(300, 300)]
    detected = [_star(11, 9)]  # only the first reference star is still detectable

    matched = _match_reference_stars(detected, reference)

    assert len(matched) == 1
    assert matched[0]["x"] == 11


def test_match_reference_stars_ignores_matches_beyond_match_radius() -> None:
    reference = [_star(10, 10)]
    detected = [_star(30, 30)]  # far outside the default match radius

    assert _match_reference_stars(detected, reference) == []


def test_match_reference_stars_is_one_to_one() -> None:
    """Two reference stars close to the same single detection must not both claim it."""
    reference = [_star(10, 10), _star(11, 11)]
    detected = [_star(10.5, 10.5)]

    matched = _match_reference_stars(detected, reference)

    assert len(matched) == 1
