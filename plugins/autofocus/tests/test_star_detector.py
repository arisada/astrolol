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

from pathlib import Path

from astropy.io import fits

from plugins.autofocus.star_detector import (
    _compute_hfd,
    _detect_sync,
    _match_reference_stars,
    _measure_star,
    _sigma_clip_mask,
    _suppress_hot_pixels,
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


# ── Whole-frame detection on synthetic fields ──────────────────────────────────
#
# Stars keep a constant total flux while their FWHM grows (as a real star does
# when defocused), so a wide star is dim per pixel but just as bright overall.

_FRAME = (600, 800)
_FLUX = 60000.0
_NOISE = 5.0
_BACKGROUND = 100.0


def _field(
    tmp_path: Path, fwhm: float, n_stars: int = 20, hot_pixels: int = 0, seed: int = 0,
    with_stars: bool = True,
) -> tuple[str, list[tuple[float, float]], list[tuple[int, int]]]:
    rng = np.random.default_rng(seed)
    h, w = _FRAME
    data = _BACKGROUND + rng.normal(0.0, _NOISE, size=_FRAME)
    sigma = fwhm / 2.3548
    margin = max(25.0, 3.5 * sigma)
    centres: list[tuple[float, float]] = []
    while with_stars and len(centres) < n_stars:
        c = (rng.uniform(margin, w - margin), rng.uniform(margin, h - margin))
        if all(np.hypot(c[0] - o[0], c[1] - o[1]) > 6 * sigma + 10 for o in centres):
            centres.append(c)
    yy, xx = np.mgrid[0:h, 0:w]
    for cx, cy in centres:
        lo_x, hi_x = int(cx - 5 * sigma - 2), int(cx + 5 * sigma + 3)
        lo_y, hi_y = int(cy - 5 * sigma - 2), int(cy + 5 * sigma + 3)
        sx, sy = xx[lo_y:hi_y, lo_x:hi_x], yy[lo_y:hi_y, lo_x:hi_x]
        data[lo_y:hi_y, lo_x:hi_x] += _FLUX / (2 * np.pi * sigma ** 2) * np.exp(
            -((sx - cx) ** 2 + (sy - cy) ** 2) / (2 * sigma ** 2)
        )
    hot = [(int(rng.integers(0, h)), int(rng.integers(0, w))) for _ in range(hot_pixels)]
    for r, c in hot:
        data[r, c] += rng.uniform(300, 5000)
    path = tmp_path / "field.fits"
    fits.PrimaryHDU(data.astype(np.float32)).writeto(path, overwrite=True)
    return str(path), centres, hot


@pytest.mark.parametrize("metric", ["fwhm", "hfd"])
@pytest.mark.parametrize("fwhm", [2.5, 6.0, 12.0, 25.0, 40.0])
def test_detects_and_measures_stars_from_sharp_to_very_defocused(
    tmp_path: Path, fwhm: float, metric: str,
) -> None:
    """Regression: a small fixed detection kernel found nothing (or only noise) once
    stars were defocused to tens of pixels, though they were obvious blobs."""
    path, centres, _ = _field(tmp_path, fwhm)
    value, count, stars = _detect_sync(path, metric)
    assert count >= 0.7 * len(centres), f"found {count}/{len(centres)} stars at fwhm={fwhm}"
    assert value == pytest.approx(fwhm, rel=0.15)
    assert len(stars) == count


@pytest.mark.parametrize("fwhm", [3.0, 12.0, 30.0])
def test_hot_pixels_are_not_reported_as_stars(tmp_path: Path, fwhm: float) -> None:
    """Regression: hot pixels keep their full peak at any focus position, so on a
    defocused frame they were what the detector locked on to."""
    path, centres, hot = _field(tmp_path, fwhm, n_stars=15, hot_pixels=80)
    value, count, stars = _detect_sync(path, "fwhm")
    assert count <= len(centres)
    for star in stars:
        assert min(np.hypot(star["x"] - c, star["y"] - r) for r, c in hot) > 3.0
    assert value == pytest.approx(fwhm, rel=0.15)


def test_a_frame_with_only_hot_pixels_has_no_stars(tmp_path: Path) -> None:
    path, _, _ = _field(tmp_path, 10.0, hot_pixels=150, with_stars=False)
    assert _detect_sync(path, "fwhm") == (0.0, 0, [])
    assert _detect_sync(path, "hfd") == (0.0, 0, [])


def test_suppress_hot_pixels_removes_spikes_but_keeps_a_sharp_star() -> None:
    rng = np.random.default_rng(1)
    data = 100.0 + rng.normal(0.0, 5.0, size=(80, 80))
    yy, xx = np.mgrid[0:80, 0:80]
    data += 3000.0 * np.exp(-((xx - 60) ** 2 + (yy - 60) ** 2) / (2 * 0.8 ** 2))  # FWHM ~1.9 px
    star_before = data[58:63, 58:63].copy()
    data[10, 10] += 2000.0
    data[30, 40] += 900.0
    cleaned, n_hot = _suppress_hot_pixels(data)
    assert n_hot == 2
    assert cleaned[10, 10] < 150 and cleaned[30, 40] < 150
    np.testing.assert_array_equal(cleaned[58:63, 58:63], star_before)


def test_reference_stars_that_are_all_lost_report_no_stars(tmp_path: Path) -> None:
    """Measuring some unrelated population instead would put a bogus point on the curve."""
    path, _, _ = _field(tmp_path, 6.0)
    far_away = [{"x": 5000.0, "y": 5000.0, "fwhm": 6.0}]
    assert _detect_sync(path, "fwhm", reference_stars=far_away) == (0.0, 0, [])


def test_reference_stars_restrict_the_measurement_to_matching_stars(tmp_path: Path) -> None:
    path, centres, _ = _field(tmp_path, 6.0)
    refs = [{"x": cx, "y": cy, "fwhm": 6.0} for cx, cy in centres[:5]]
    _, count, stars = _detect_sync(path, "fwhm", reference_stars=refs)
    assert 1 <= count <= 5
    assert all(min(np.hypot(st["x"] - cx, st["y"] - cy) for cx, cy in centres[:5]) < 2.0 for st in stars)


@pytest.mark.parametrize("fwhm", [1.2, 1.5, 1.8])
@pytest.mark.parametrize("seed", range(8))
def test_bright_sharp_stars_near_perfect_focus_are_not_dropped(fwhm: float, seed: int) -> None:
    """Regression: a minimum-width cut dropped the brightest stars once focus got good.
    A sharp star's moment-based width is biased low by pixel sampling (a pixel-centred
    one can read under 1 px), and only the bright stars show it — noise inflates the
    estimate of faint ones — so it was the brightest stars that went missing."""
    from plugins.autofocus.star_detector import _find_blobs

    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:120, 0:120]
    cx, cy = 60 + rng.uniform(-0.5, 0.5), 60 + rng.uniform(-0.5, 0.5)
    sigma = fwhm / 2.3548
    data = 1000.0 + rng.normal(0.0, 10.0, size=(120, 120))
    data += 3e5 / (2 * np.pi * sigma ** 2) * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
    data, _ = _suppress_hot_pixels(data)
    found = [b for b in _find_blobs(data) if np.hypot(b[0] - cx, b[1] - cy) < 4]
    assert found
    assert _measure_star(data, found[0][0], found[0][1], found[0][2]) is not None


def test_measure_star_rejects_a_lone_hot_pixel() -> None:
    rng = np.random.default_rng(3)
    data = 100.0 + rng.normal(0.0, 5.0, size=(80, 80))
    data[40, 40] += 4000.0
    assert _measure_star(data, 40.0, 40.0, 1.0) is None
