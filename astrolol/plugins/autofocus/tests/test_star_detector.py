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

from astrolol.plugins.autofocus.star_detector import (
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
    from astrolol.plugins.autofocus.star_detector import _find_blobs

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


# ---------------------------------------------------------------------------
# Tiling: memory stays bounded and stars on tile borders are neither lost nor doubled
# ---------------------------------------------------------------------------

def _star_at(data: np.ndarray, cx: float, cy: float, fwhm: float, flux: float) -> None:
    sigma = fwhm / 2.3548
    r = int(6 * sigma) + 2
    y0, x0 = int(cy) - r, int(cx) - r
    yy, xx = np.mgrid[y0:y0 + 2 * r + 1, x0:x0 + 2 * r + 1]
    data[y0:y0 + 2 * r + 1, x0:x0 + 2 * r + 1] += flux / (2 * np.pi * sigma ** 2) * np.exp(
        -((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2)
    )


def test_stars_on_tile_borders_and_corners_are_found_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from astrolol.plugins.autofocus import star_detector

    monkeypatch.setattr(star_detector, "_TILE", 128)
    monkeypatch.setattr(star_detector, "_HALO", 48)
    rng = np.random.default_rng(3)
    data = _BACKGROUND + rng.normal(0.0, _NOISE, size=(400, 520))
    # On the borders (x or y = 127.5 / 128 / 255.5 / 256), at a crossing and in the image corners.
    centres = [(128.0, 60.0), (127.5, 200.0), (60.0, 256.0), (300.0, 255.5), (256.0, 128.0),
               (30.0, 30.0), (490.0, 370.0), (30.0, 370.0), (490.0, 30.0)]
    for cx, cy in centres:
        _star_at(data, cx, cy, 4.0, _FLUX)
    path = tmp_path / "tiles.fits"
    fits.PrimaryHDU(data.astype(np.float32)).writeto(path, overwrite=True)

    _, count, stars = _detect_sync(str(path), "fwhm")

    assert count == len(centres)
    for cx, cy in centres:
        near = [s for s in stars if np.hypot(s["x"] - cx, s["y"] - cy) < 1.5]
        assert len(near) == 1, f"star at ({cx}, {cy}) found {len(near)} times"


def test_unsigned_16_bit_files_are_read_with_their_scaling(tmp_path: Path) -> None:
    """Cameras write uint16 as int16 + BZERO=32768; the tiles must undo that."""
    rng = np.random.default_rng(4)
    data = _BACKGROUND + rng.normal(0.0, _NOISE, size=_FRAME)
    _star_at(data, 300.0, 200.0, 5.0, _FLUX)
    path = tmp_path / "u16.fits"
    fits.PrimaryHDU(np.clip(data, 0, 65535).astype(np.uint16)).writeto(path, overwrite=True)
    with fits.open(path) as hdul:
        assert hdul[0].header["BZERO"] == 32768

    value, count, stars = _detect_sync(str(path), "fwhm")

    assert count == 1
    assert np.hypot(stars[0]["x"] - 300.0, stars[0]["y"] - 200.0) < 1.0
    assert value == pytest.approx(5.0, rel=0.2)


def test_a_20_megapixel_frame_needs_a_fraction_of_its_float64_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the whole frame was converted to float64 (160 MB at 20 MP) and filtered in one go,
    which got the process OOM-killed on a small Pi."""
    import tracemalloc
    from astrolol.plugins.autofocus import star_detector

    monkeypatch.setattr(star_detector, "_workers", lambda: 1)   # memory of one tile in flight

    h, w = 3672, 5496   # ASI183 at bin 1
    rng = np.random.default_rng(5)
    data = np.full((h, w), 1000, dtype=np.uint16)
    data += rng.integers(0, 40, size=(h, w), dtype=np.uint16)
    # One star in the middle of a tile and one across a tile border.
    for cx, cy in [(2000.0, 1500.0), (1024.0, 3000.0)]:
        sigma = 2.0
        yy, xx = np.mgrid[int(cy) - 14:int(cy) + 15, int(cx) - 14:int(cx) + 15]
        data[int(cy) - 14:int(cy) + 15, int(cx) - 14:int(cx) + 15] += (
            20000 / (2 * np.pi * sigma ** 2) * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
        ).astype(np.uint16)
    path = tmp_path / "big.fits"
    fits.PrimaryHDU(data).writeto(path)
    del data

    tracemalloc.start()
    try:
        _, count, stars = _detect_sync(str(path), "hfd")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert count == 2
    assert {round(s["x"] / 100) for s in stars} == {20, 10}
    assert peak < 120 * 1024 * 1024, f"peak {peak / 1e6:.0f} MB"


def test_local_maxima_match_a_maximum_filter() -> None:
    from scipy import ndimage as ndi
    from astrolol.plugins.autofocus import star_detector
    from astrolol.plugins.autofocus.star_detector import _local_maxima

    rng = np.random.default_rng(7)
    z = rng.normal(0.0, 3.0, size=(90, 120)).astype(np.float32)
    z[10, 10] = z[10, 11] = 40.0   # a tie
    z[0, 0] = 30.0                 # in a corner
    z[89, 119] = 30.0
    for r in (2, 3, 4):
        expected = np.argwhere((z == ndi.maximum_filter(z, size=2 * r + 1)) & (z > 6.0))
        ys, xs = _local_maxima(z, r, 6.0)
        assert sorted(zip(ys.tolist(), xs.tolist())) == sorted(map(tuple, expected.tolist()))
    # The fallback for huge bright areas gives the same answer.
    old = star_detector._MAX_PEAK_PIXELS
    star_detector._MAX_PEAK_PIXELS = 0
    try:
        ys, xs = _local_maxima(z, 3, 6.0)
    finally:
        star_detector._MAX_PEAK_PIXELS = old
    expected = np.argwhere((z == ndi.maximum_filter(z, size=7)) & (z > 6.0))
    assert sorted(zip(ys.tolist(), xs.tolist())) == sorted(map(tuple, expected.tolist()))


def test_threads_give_the_same_stars_as_one_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from astrolol.plugins.autofocus import star_detector

    monkeypatch.setattr(star_detector, "_TILE", 128)
    monkeypatch.setattr(star_detector, "_HALO", 48)
    path, centres, _ = _field(tmp_path, 5.0, n_stars=20)
    monkeypatch.setattr(star_detector, "_workers", lambda: 1)
    serial = _detect_sync(path, "hfd")
    monkeypatch.setattr(star_detector, "_workers", lambda: 4)
    threaded = _detect_sync(path, "hfd")
    assert threaded == serial
    assert serial[1] >= 0.7 * len(centres)


@pytest.mark.parametrize("fwhm", [40.0, 60.0, 90.0])
def test_very_defocused_stars_are_found_across_tile_borders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fwhm: float,
) -> None:
    """Autofocus starts from badly out-of-focus frames: huge, dim stars whose kernel and measuring
    stamp (up to ~230 px at FWHM 90) are far larger than a tile's core, and some sit on a border."""
    from astrolol.plugins.autofocus import star_detector

    monkeypatch.setattr(star_detector, "_TILE", 512)   # smaller than the stars' own stamp
    rng = np.random.default_rng(11)
    data = 1000.0 + rng.normal(0.0, 8.0, size=(1500, 2300))
    centres = [(1024.0, 700.0), (1700.0, 512.0), (512.0, 1024.0), (1400.0, 1000.0), (2000.0, 1150.0)]
    for cx, cy in centres:
        _star_at(data, cx, cy, fwhm, 3e5)
    path = tmp_path / "defocused.fits"
    fits.PrimaryHDU(data.astype(np.float32)).writeto(path, overwrite=True)

    value, count, stars = _detect_sync(str(path), "fwhm")

    assert count == len(centres)
    assert value == pytest.approx(fwhm, rel=0.15)
    for cx, cy in centres:
        assert sum(np.hypot(s["x"] - cx, s["y"] - cy) < 3.0 for s in stars) == 1
