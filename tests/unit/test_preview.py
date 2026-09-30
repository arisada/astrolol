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


def test_stretch_percentiles_are_configurable(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    data = rng.integers(100, 4000, size=(64, 64), dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "noise.fits", data)

    default_stats = fits_to_jpeg(fits_path, tmp_path / "default.jpg")
    wide_stats = fits_to_jpeg(
        fits_path, tmp_path / "wide.jpg", black_percentile=10.0, white_percentile=90.0
    )
    assert wide_stats["stretch_low"] < default_stats["stretch_low"]
    assert wide_stats["stretch_high"] < default_stats["stretch_high"]


def test_jpeg_quality_changes_output_size(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    data = rng.integers(0, 65535, size=(256, 256), dtype=np.uint16)
    fits_path = _write_uint16_fits(tmp_path / "rand.fits", data)

    low_path = tmp_path / "low.jpg"
    high_path = tmp_path / "high.jpg"
    fits_to_jpeg(fits_path, low_path, quality=10)
    fits_to_jpeg(fits_path, high_path, quality=95)
    assert low_path.stat().st_size < high_path.stat().st_size


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
