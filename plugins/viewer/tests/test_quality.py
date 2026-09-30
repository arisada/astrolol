from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from plugins.viewer.quality import compute_quality


def _write(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(data.astype(np.uint16)).writeto(path, overwrite=True)
    return path


def _gaussian_star(shape: tuple[int, int], cx: float, cy: float, amplitude: float, sigma: float) -> np.ndarray:
    y, x = np.indices(shape)
    return amplitude * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma ** 2)))


@pytest.mark.asyncio
async def test_star_field_is_detected(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    shape = (200, 200)
    background = 500 + rng.normal(0, 5, size=shape)
    frame = background.copy()
    for cx, cy in [(40, 40), (100, 60), (160, 150)]:
        frame += _gaussian_star(shape, cx, cy, amplitude=3000, sigma=2.5)
    path = _write(tmp_path / "stars.fits", np.clip(frame, 0, 65535))

    bg_median, star_count, hfr = await compute_quality(path)

    assert bg_median is not None and abs(bg_median - 500) < 50
    assert star_count is not None and star_count >= 2
    assert hfr is not None and hfr > 0


@pytest.mark.asyncio
async def test_pure_noise_frame_has_no_stars(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    frame = 500 + rng.normal(0, 3, size=(100, 100))
    path = _write(tmp_path / "noise.fits", np.clip(frame, 0, 65535))

    bg_median, star_count, hfr = await compute_quality(path)

    assert star_count == 0


@pytest.mark.asyncio
async def test_missing_data_does_not_raise(tmp_path: Path) -> None:
    path = tmp_path / "empty.fits"
    fits.PrimaryHDU().writeto(path, overwrite=True)

    bg_median, star_count, hfr = await compute_quality(path)

    assert (bg_median, star_count, hfr) == (None, None, None)
