from pathlib import Path

import numpy as np
from astropy.io import fits

from PIL import Image

from astrolol.imaging.preview import fits_to_jpeg, fits_to_jpeg_linear, fits_to_thumbnail


def _write_uint16_fits(path: Path, data: np.ndarray) -> Path:
    """Write FITS data as on-disk uint16 (BITPIX=16, BZERO=32768), like a real camera."""
    hdu = fits.PrimaryHDU(data.astype(np.uint16))
    hdu.writeto(path, overwrite=True)
    return path


def test_histogram_uses_sensor_full_scale_not_sample_range(tmp_path: Path) -> None:
    """A frame whose brightest pixel is far below saturation must still report the
    sensor's full-scale value as hist_max, not the sample's own max — otherwise the
    histogram silently rescales every frame and clipping/underexposure can't be judged."""
    data = np.full((64, 64), 500, dtype=np.uint16)
    data[0, 0] = 2000  # well below 16-bit saturation (65535)
    fits_path = _write_uint16_fits(tmp_path / "dim.fits", data)
    stats = fits_to_jpeg(fits_path, tmp_path / "dim.jpg")
    assert stats["hist_min"] == 0.0
    assert stats["hist_max"] == 65535.0


def test_clipped_highlights_land_at_the_last_bin(tmp_path: Path) -> None:
    data = np.full((64, 64), 65535, dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "clipped.fits", data)
    stats = fits_to_jpeg(fits_path, tmp_path / "clipped.jpg")
    assert stats["histogram"][-1] > 0
    assert sum(stats["histogram"][:-1]) == 0


def test_stretch_parameters_are_configurable(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    data = rng.normal(1000, 20, size=(64, 64)).astype(np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "noise.fits", data)

    default_stats = fits_to_jpeg(fits_path, tmp_path / "default.jpg")
    custom_stats = fits_to_jpeg(fits_path, tmp_path / "custom.jpg", target_bg=0.4, shadows_sigma=-1.0)
    assert custom_stats["stretch_low"] > default_stats["stretch_low"]
    assert custom_stats["stretch_midtone"] != default_stats["stretch_midtone"]


def test_jpeg_quality_changes_output_size(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    data = rng.integers(0, 65535, size=(256, 256), dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "rand.fits", data)

    low_path = tmp_path / "low.jpg"
    high_path = tmp_path / "high.jpg"
    fits_to_jpeg(fits_path, low_path, quality=10)
    fits_to_jpeg(fits_path, high_path, quality=95)
    assert low_path.stat().st_size < high_path.stat().st_size


def test_fully_saturated_frame_renders_white_not_black(tmp_path: Path) -> None:
    """Regression: a perfectly flat frame (low == high, most commonly a fully
    saturated or fully black frame) collapsed the relative stretch to 0 everywhere
    regardless of how bright that flat level actually was, rendering a saturated
    frame pitch black instead of white."""
    data = np.full((64, 64), 65535, dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "saturated.fits", data)
    out_path = tmp_path / "saturated.jpg"
    fits_to_jpeg(fits_path, out_path)
    with Image.open(out_path) as img:
        assert np.array(img).mean() > 250  # near-white, not near-black


def test_fully_black_frame_still_renders_black(tmp_path: Path) -> None:
    data = np.zeros((64, 64), dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "black.fits", data)
    out_path = tmp_path / "black.jpg"
    fits_to_jpeg(fits_path, out_path)
    with Image.open(out_path) as img:
        assert np.array(img).mean() < 5


def test_fully_saturated_frame_renders_white_in_linear_mode(tmp_path: Path) -> None:
    data = np.full((64, 64), 65535, dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "saturated_linear.fits", data)
    out_path = tmp_path / "saturated_linear.jpg"
    fits_to_jpeg_linear(fits_path, out_path)
    with Image.open(out_path) as img:
        assert np.array(img).mean() > 250


def test_fully_saturated_frame_renders_white_in_thumbnail(tmp_path: Path) -> None:
    data = np.full((64, 64), 65535, dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "saturated_thumb.fits", data)
    out_path = tmp_path / "saturated_thumb.jpg"
    fits_to_thumbnail(fits_path, out_path)
    with Image.open(out_path) as img:
        assert np.array(img).mean() > 250


def test_linear_preview_uses_an_absolute_scale_not_per_frame_minmax(tmp_path: Path) -> None:
    """Regression: fits_to_jpeg_linear used to stretch each frame from its own min to
    its own max, so two genuinely different-brightness frames (e.g. two flats shot at
    different exposures, each with little internal dynamic range) rendered identically
    once independently renormalised to fill [0, 255]. Linear must stay anchored to the
    sensor's fixed full-scale ADU so brightness stays comparable across frames."""
    dim = np.full((64, 64), 32768, dtype=np.uint16)   # ~50% of 16-bit full well
    bright = np.full((64, 64), 43253, dtype=np.uint16)  # ~66% of 16-bit full well
    dim_path = _write_uint16_fits(tmp_path / "dim_flat.fits", dim)
    bright_path = _write_uint16_fits(tmp_path / "bright_flat.fits", bright)

    fits_to_jpeg_linear(dim_path, tmp_path / "dim_flat.jpg")
    fits_to_jpeg_linear(bright_path, tmp_path / "bright_flat.jpg")

    with Image.open(tmp_path / "dim_flat.jpg") as dim_img, Image.open(tmp_path / "bright_flat.jpg") as bright_img:
        dim_mean = float(np.array(dim_img).mean())
        bright_mean = float(np.array(bright_img).mean())

    assert bright_mean > dim_mean + 20  # clearly different, not independently renormalised to match
    assert abs(dim_mean - 255 * (32768 / 65535)) < 2
    assert abs(bright_mean - 255 * (43253 / 65535)) < 2


def test_linear_preview_still_works_with_integer_fits(tmp_path: Path) -> None:
    data = np.full((64, 64), 1234, dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "linear.fits", data)
    out_path = tmp_path / "linear.jpg"
    fits_to_jpeg_linear(fits_path, out_path, quality=85)
    assert out_path.exists()


def test_thumbnail_is_downscaled_to_max_dim(tmp_path: Path) -> None:
    rng = np.random.default_rng(2)
    data = rng.integers(100, 4000, size=(1200, 1600), dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "big.fits", data)
    out_path = tmp_path / "thumb.jpg"

    fits_to_thumbnail(fits_path, out_path, max_dim=256)

    assert out_path.exists()
    with Image.open(out_path) as img:
        assert max(img.size) <= 256


def test_thumbnail_handles_a_frame_smaller_than_max_dim(tmp_path: Path) -> None:
    data = np.full((64, 64), 1000, dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "small.fits", data)
    out_path = tmp_path / "small_thumb.jpg"

    fits_to_thumbnail(fits_path, out_path, max_dim=256)

    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.size == (64, 64)


# --- Strip-wise loader / PreviewBase --------------------------------------------

import os
import tracemalloc

import pytest

from astrolol.imaging import preview as preview_mod
from astrolol.imaging.preview import (
    PreviewBaseCache,
    load_preview_base,
    render_auto,
    render_linear,
)


def _reference_bin(data: np.ndarray, k: int) -> np.ndarray:
    h, w = data.shape[0] // k, data.shape[1] // k
    return data[: h * k, : w * k].astype(np.float64).reshape(h, k, w, k).mean(axis=(1, 3))


def test_base_is_an_exact_block_mean_across_strip_boundaries(tmp_path: Path, monkeypatch) -> None:
    """Tiny strips (and dimensions that divide neither the strip height nor k) force
    many strips, a short last strip and dropped edge rows/columns — the result must
    still equal a whole-array block mean."""
    monkeypatch.setattr(preview_mod, "_STRIP_PIXELS", 1000)
    rng = np.random.default_rng(3)
    data = rng.integers(0, 65535, size=(203, 157), dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "odd.fits", data)

    base = load_preview_base(fits_path, max_dim=50)

    assert base.bin_factor == 5
    assert base.data.shape == (40, 31)
    np.testing.assert_allclose(base.data, _reference_bin(data, 5), rtol=0, atol=0.01)
    assert (base.width, base.height) == (157, 203)


def test_histogram_and_mean_are_full_resolution(tmp_path: Path) -> None:
    """A single hot pixel must still be counted at the right edge of the histogram,
    even though binning averages it into its neighbours in the preview image —
    and pixels beyond the last whole bin block still count."""
    data = np.full((513, 513), 1000, dtype=np.uint16)
    data[100, 100] = 65535
    data[512, 512] = 65535  # in the dropped edge row/column
    fits_path = _write_uint16_fits(tmp_path / "hot.fits", data)

    base = load_preview_base(fits_path, max_dim=64)

    assert base.bin_factor > 1
    assert base.data.max() < 65535  # averaged away in the binned image...
    assert base.histogram[-1] == 2  # ...but not in the histogram
    assert base.histogram.sum() == data.size
    assert base.mean == pytest.approx(float(data.astype(np.float64).mean()))


def test_loading_a_large_frame_never_materialises_it(tmp_path: Path) -> None:
    """Peak memory must stay well below the raw frame size — the old loader held
    the frame as uint16 + float32 + a PIL float copy (~5× the raw size)."""
    data = np.random.default_rng(4).integers(0, 4000, size=(3000, 4000), dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "large.fits", data)
    raw_bytes = data.nbytes
    del data

    tracemalloc.start()
    try:
        load_preview_base(fits_path, max_dim=500)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < raw_bytes / 2


def test_float_fits_uses_its_own_max_and_ignores_nan(tmp_path: Path) -> None:
    data = np.full((32, 32), 10.0, dtype=np.float32)
    data[0, 0] = 250.0
    data[1, 1] = np.nan
    fits_path = tmp_path / "float.fits"
    fits.PrimaryHDU(data).writeto(fits_path)

    base = load_preview_base(fits_path)

    assert base.adu_max == 250.0
    assert base.hist_max == 250.0
    assert np.isfinite(base.data).all()


def test_signed_int16_without_bzero_uses_int16_full_scale(tmp_path: Path) -> None:
    fits_path = tmp_path / "signed.fits"
    fits.PrimaryHDU(np.full((16, 16), 1000, dtype=np.int16)).writeto(fits_path)
    assert load_preview_base(fits_path).adu_max == 32767.0


def test_rendering_does_not_mutate_the_base(tmp_path: Path) -> None:
    data = np.random.default_rng(5).integers(100, 4000, size=(64, 64), dtype=np.uint16)
    base = load_preview_base(_write_uint16_fits(tmp_path / "b.fits", data))
    before = base.data.copy()
    render_auto(base, tmp_path / "a.jpg", target_bg=0.4, shadows_sigma=-1.0)
    render_linear(base, tmp_path / "l.jpg")
    np.testing.assert_array_equal(base.data, before)


def test_cache_reuses_the_base_until_the_file_changes(tmp_path: Path, monkeypatch) -> None:
    fits_path = _write_uint16_fits(tmp_path / "c.fits", np.full((32, 32), 100, dtype=np.uint16))
    loads: list[Path] = []
    real_load = preview_mod.load_preview_base
    monkeypatch.setattr(preview_mod, "load_preview_base", lambda p, m: loads.append(p) or real_load(p, m))
    cache = PreviewBaseCache(capacity=2)

    first = cache.load(fits_path)
    assert cache.load(fits_path) is first
    assert len(loads) == 1

    # Overwritten in place (like the imager's per-camera temp FITS for unsaved frames).
    _write_uint16_fits(fits_path, np.full((32, 32), 200, dtype=np.uint16))
    st = fits_path.stat()
    os.utime(fits_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    second = cache.load(fits_path)
    assert second is not first
    assert float(second.data.mean()) == pytest.approx(200.0)


def test_cache_evicts_least_recently_used(tmp_path: Path) -> None:
    paths = [
        _write_uint16_fits(tmp_path / f"{i}.fits", np.full((8, 8), i, dtype=np.uint16)) for i in range(3)
    ]
    cache = PreviewBaseCache(capacity=2)
    a = cache.load(paths[0])
    cache.load(paths[1])
    cache.load(paths[0])          # refresh 0 → 1 is now least recent
    cache.load(paths[2])          # evicts 1
    assert cache.load(paths[0]) is a
    assert len(cache._items) == 2


# --- MTF auto-stretch ------------------------------------------------------------

from astrolol.imaging.preview import auto_stretch_params, auto_stretch_stats, mtf


def _sky(shape=(400, 600), bg=1000.0, sigma=20.0, seed=0) -> np.ndarray:
    return np.random.default_rng(seed).normal(bg, sigma, size=shape)


def _add_stars(data: np.ndarray, count: int, peak: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    h, w = data.shape
    for y, x in zip(rng.integers(3, h - 3, count), rng.integers(3, w - 3, count)):
        data[y - 1: y + 2, x - 1: x + 2] += peak / 3
        data[y, x] += peak
    return data


def _rendered_median(fits_path: Path, tmp_path: Path, **kwargs) -> float:
    out = tmp_path / (fits_path.stem + ".jpg")
    fits_to_jpeg(fits_path, out, **kwargs)
    with Image.open(out) as img:
        return float(np.median(np.array(img)))


def test_mtf_basics() -> None:
    assert mtf(0.5, 0.3) == pytest.approx(0.3)      # m = 0.5 is the identity
    assert mtf(0.1, 0.1) == pytest.approx(0.5)      # m maps to 0.5
    assert (mtf(0.1, 0.0), mtf(0.1, 1.0)) == (0.0, 1.0)


def test_background_lands_at_the_target_brightness(tmp_path: Path) -> None:
    fits_path = _write_uint16_fits(tmp_path / "sky.fits", np.clip(_add_stars(_sky(), 50, 20000), 0, 65535))
    assert abs(_rendered_median(fits_path, tmp_path) - 0.25 * 255) < 6
    assert abs(_rendered_median(fits_path, tmp_path, target_bg=0.1) - 0.1 * 255) < 6


def test_sparse_and_dense_fields_get_the_same_background(tmp_path: Path) -> None:
    """The old 99th-percentile white point fell inside the noise on sparse fields
    (crushing the background to black, noise to salt-and-pepper) but on stars in
    dense ones. The MTF stretch is anchored to the background and its noise, so
    both render the sky at the same brightness."""
    sparse = np.clip(_add_stars(_sky(seed=2), 10, 20000, seed=3), 0, 65535)
    dense = np.clip(_add_stars(_sky(seed=4), 4000, 20000, seed=5), 0, 65535)
    m_sparse = _rendered_median(_write_uint16_fits(tmp_path / "sparse.fits", sparse), tmp_path)
    m_dense = _rendered_median(_write_uint16_fits(tmp_path / "dense.fits", dense), tmp_path)
    assert abs(m_sparse - m_dense) < 8
    assert 40 < m_sparse < 90


def test_black_point_is_k_sigma_below_the_background(tmp_path: Path) -> None:
    base = load_preview_base(_write_uint16_fits(tmp_path / "bp.fits", _sky()))
    stats = auto_stretch_stats(base, shadows_sigma=-2.8)
    assert stats["stretch_low"] == pytest.approx(stats["display_median"] - 2.8 * stats["display_sigma"], rel=1e-4)
    assert stats["stretch_high"] == 65535.0


def test_highlights_are_compressed_not_clipped(tmp_path: Path) -> None:
    data = _sky(shape=(64, 64))
    data[10, 10] = 20000
    data[40, 40] = 50000
    base = load_preview_base(_write_uint16_fits(tmp_path / "hl.fits", data))
    low, high, m = auto_stretch_params(base)
    px = preview_mod._mtf_to_uint8(base.data, low, high, m, base.adu_max)
    assert px[10, 10] < px[40, 40] < 255


def test_bright_background_gets_no_midtone_boost(tmp_path: Path) -> None:
    """When the background already sits above the target after the black point is
    applied (here: a black point deep enough to clamp to 0), the stretch must not
    darken it down to the target — a bright frame should look bright."""
    base = load_preview_base(_write_uint16_fits(tmp_path / "flat.fits", _sky(bg=30000, sigma=3000)))
    low, _, m = auto_stretch_params(base, target_bg=0.25, shadows_sigma=-10.0)
    assert low == 0.0
    assert m == 0.5


def test_saturated_pct_counts_full_resolution_and_left_shifted_data(tmp_path: Path) -> None:
    data = _sky(shape=(200, 200))
    data.ravel()[:200] = 65535   # 0.5% at 16-bit full scale
    data.ravel()[200:400] = 65520  # 0.5% at 12-bit full scale, left-shifted into 16 bits
    stats = auto_stretch_stats(load_preview_base(_write_uint16_fits(tmp_path / "sat.fits", data), max_dim=20))
    assert stats["saturated_pct"] == pytest.approx(1.0)


def test_saturated_pct_is_unknown_for_float_data(tmp_path: Path) -> None:
    fits_path = tmp_path / "float_sat.fits"
    fits.PrimaryHDU(_sky(shape=(32, 32)).astype(np.float32)).writeto(fits_path)
    assert auto_stretch_stats(load_preview_base(fits_path))["saturated_pct"] is None


def test_noise_sigma_is_full_resolution(tmp_path: Path) -> None:
    """noise_sigma is the per-pixel noise (exposure decisions); display_sigma is the
    binned preview's, which averaging lowers."""
    base = load_preview_base(_write_uint16_fits(tmp_path / "n.fits", _sky(shape=(800, 800))), max_dim=200)
    stats = auto_stretch_stats(base)
    assert stats["noise_sigma"] == pytest.approx(20.0, rel=0.1)
    assert stats["median"] == pytest.approx(1000.0, abs=2)
    assert stats["display_sigma"] == pytest.approx(20.0 / base.bin_factor, rel=0.15)


# --- Bayer / colour ----------------------------------------------------------------

from astrolol.imaging.preview import _bayer_pattern


def _mosaic(r: np.ndarray, g: np.ndarray, b: np.ndarray, pattern: str = "RGGB") -> np.ndarray:
    """Build a CFA frame from full-size R/G/B planes for *pattern* at (0, 0)."""
    planes = {"R": r, "G": g, "B": b}
    out = np.empty_like(r)
    for i, colour in enumerate(pattern):
        out[i // 2::2, i % 2::2] = planes[colour][i // 2::2, i % 2::2]
    return out


def _write_bayer_fits(path: Path, data: np.ndarray, pattern: str = "RGGB", **extra) -> Path:
    hdu = fits.PrimaryHDU(np.clip(data, 0, 65535).astype(np.uint16))
    hdu.header["BAYERPAT"] = pattern
    for key, value in extra.items():
        hdu.header[key] = value
    hdu.writeto(path, overwrite=True)
    return path


def _flat_planes(shape=(120, 160), levels=(1000.0, 2000.0, 3000.0)):
    return tuple(np.full(shape, v) for v in levels)


@pytest.mark.parametrize("pattern", ["RGGB", "BGGR", "GRBG", "GBRG"])
def test_superpixel_debayer_recovers_each_channel(tmp_path: Path, pattern: str) -> None:
    fits_path = _write_bayer_fits(tmp_path / "cfa.fits", _mosaic(*_flat_planes(), pattern=pattern), pattern)
    base = load_preview_base(fits_path)
    assert base.is_color and base.bayer_pattern == pattern
    for c, level in enumerate((1000.0, 2000.0, 3000.0)):
        np.testing.assert_allclose(base.data[..., c], level)


def test_bayer_offsets_shift_the_pattern() -> None:
    header = fits.Header({"BAYERPAT": "RGGB", "XBAYROFF": 1, "YBAYROFF": 0})
    assert _bayer_pattern(header) == "GRBG"
    header["YBAYROFF"] = 1
    assert _bayer_pattern(header) == "BGGR"
    assert _bayer_pattern(fits.Header({"BAYERPAT": "XYZW"})) is None
    assert _bayer_pattern(fits.Header()) is None


def test_offset_header_is_applied_when_loading(tmp_path: Path) -> None:
    # Data laid out as GRBG at (0, 0), described as RGGB starting one column in.
    data = _mosaic(*_flat_planes(), pattern="GRBG")
    base = load_preview_base(_write_bayer_fits(tmp_path / "off.fits", data, "RGGB", XBAYROFF=1))
    np.testing.assert_allclose(base.data[0, 0], [1000.0, 2000.0, 3000.0])


def test_bayer_bin_factor_is_even_and_exact_across_strips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preview_mod, "_STRIP_PIXELS", 2000)
    rng = np.random.default_rng(6)
    r, g, b = (rng.normal(v, 50, size=(301, 403)) for v in (1000, 2000, 3000))
    data = np.clip(_mosaic(r, g, b), 0, 65535).astype(np.uint16)
    base = load_preview_base(_write_bayer_fits(tmp_path / "cfa_odd.fits", data), max_dim=140)

    assert base.bin_factor == 4  # ceil(403 / 140) = 3, rounded up to even
    h, w = 301 // 4, 403 // 4
    assert base.data.shape == (h, w, 3)
    crop = data[: h * 4, : w * 4].astype(np.float64)
    ref_r = crop[0::2, 0::2].reshape(h, 2, w, 2).mean(axis=(1, 3))
    ref_g = (crop[0::2, 1::2] + crop[1::2, 0::2]).reshape(h, 2, w, 2).mean(axis=(1, 3)) / 2
    ref_b = crop[1::2, 1::2].reshape(h, 2, w, 2).mean(axis=(1, 3))
    np.testing.assert_allclose(base.data, np.stack([ref_r, ref_g, ref_b], axis=-1), atol=0.01)
    # Full-resolution histograms: per channel, and they add up to every pixel.
    assert base.channel_histograms is not None
    assert base.channel_histograms.sum() == data.size
    np.testing.assert_array_equal(base.channel_histograms.sum(axis=0), base.histogram)


def _light_polluted_sky(tmp_path: Path) -> Path:
    rng = np.random.default_rng(7)
    r, g, b = (rng.normal(v, 30, size=(200, 300)) for v in (3000, 1500, 1000))
    return _write_bayer_fits(tmp_path / "lp.fits", _mosaic(r, g, b))


def _channel_medians(jpeg: Path) -> np.ndarray:
    with Image.open(jpeg) as img:
        assert img.mode == "RGB"
        return np.median(np.array(img).reshape(-1, 3), axis=0)


def test_unlinked_stretch_neutralises_a_background_cast(tmp_path: Path) -> None:
    out = tmp_path / "unlinked.jpg"
    stats = render_auto(load_preview_base(_light_polluted_sky(tmp_path)), out)
    medians = _channel_medians(out)
    assert medians.max() - medians.min() < 10  # grey background
    assert [ch["name"] for ch in stats["channels"]] == ["R", "G", "B"]
    assert stats["channels"][0]["median"] == pytest.approx(3000, abs=5)
    assert stats["channels"][2]["median"] == pytest.approx(1000, abs=5)
    # Per-channel noise, not inflated by the 2000 ADU spread between channel backgrounds.
    assert stats["noise_sigma"] == pytest.approx(30, rel=0.15)


def test_linked_stretch_keeps_the_colour_balance(tmp_path: Path) -> None:
    out = tmp_path / "linked.jpg"
    stats = render_auto(load_preview_base(_light_polluted_sky(tmp_path)), out, linked=True)
    r, _, b = _channel_medians(out)
    assert r > b + 50  # the red cast is still there
    assert len({(ch["stretch_low"], ch["stretch_midtone"]) for ch in stats["channels"]}) == 1


def test_mono_option_renders_luminance(tmp_path: Path) -> None:
    base = load_preview_base(_light_polluted_sky(tmp_path))
    render_auto(base, tmp_path / "mono.jpg", color=False)
    render_linear(base, tmp_path / "mono_lin.jpg", color=False)
    render_linear(base, tmp_path / "rgb_lin.jpg")
    for name, mode in (("mono.jpg", "L"), ("mono_lin.jpg", "L"), ("rgb_lin.jpg", "RGB")):
        with Image.open(tmp_path / name) as img:
            assert img.mode == mode


def test_mono_frames_have_no_channel_stats(tmp_path: Path) -> None:
    base = load_preview_base(_write_uint16_fits(tmp_path / "m.fits", _sky(shape=(64, 64))))
    assert not base.is_color
    assert auto_stretch_stats(base)["channels"] is None
