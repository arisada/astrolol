"""A stack travels through the rest of astrolol's imaging code like any camera's frame."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import astropy.io.fits as astropy_fits
import numpy as np
from PIL import Image

from astrolol.imaging.imager import _write_imagetyp, add_fits_header_cards
from astrolol.imaging.preview import fits_to_jpeg
from astrolol.plugins.stacked_camera.accumulator import SumAccumulator
from astrolol.plugins.stacked_camera.fits import StackInfo, write_stack_fits

SUBS = 20


def _stack(tmp_path: Path) -> tuple[Path, np.ndarray]:
    """20 faint-sky subs on a bias of 500 ADU, with one star, summed by the accumulator."""
    rng = np.random.default_rng(4)
    acc = SumAccumulator()
    for _ in range(SUBS):
        sub = rng.normal(530, 4, (120, 160))
        sub[60:64, 80:84] += 3000
        acc.add(np.clip(np.rint(sub), 0, 65535).astype(np.uint16), 2.0)
    info = StackInfo(
        subs=acc.count, exposure=acc.exposure, start=datetime.now(UTC), full_scale=acc.full_scale
    )
    path = write_stack_fits(tmp_path / "stack.fits", acc.result(), info)
    return path, acc.result().copy()


def test_the_preview_judges_a_stack_against_its_own_full_scale(tmp_path: Path) -> None:
    path, _ = _stack(tmp_path)
    stats = fits_to_jpeg(path, tmp_path / "stack.jpg")
    assert stats["hist_max"] == SUBS * 65535.0
    assert stats["stretch_high"] == SUBS * 65535.0
    assert stats["saturated_pct"] == 0.0
    # The stretch is of the order a single sub gets (the sum has more noise but also a larger
    # signal), not the extreme curve a full scale of 2**31 gives (about 1e-7 here).
    sub = np.clip(np.rint(np.random.default_rng(5).normal(530, 4, (120, 160))), 0, 65535)
    single = tmp_path / "sub.fits"
    astropy_fits.PrimaryHDU(sub.astype(np.uint16)).writeto(single)
    native = fits_to_jpeg(single, tmp_path / "sub.jpg")["stretch_midtone"]
    assert native / 10 < stats["stretch_midtone"] < native * 10


def test_the_stack_preview_shows_the_star(tmp_path: Path) -> None:
    path, _ = _stack(tmp_path)
    fits_to_jpeg(path, tmp_path / "stack.jpg")
    image = np.asarray(Image.open(tmp_path / "stack.jpg").convert("L"))
    assert image.max() > image.mean() + 40  # the star stands out of the sky


def test_a_pixel_saturated_in_every_sub_is_counted_as_saturated(tmp_path: Path) -> None:
    acc = SumAccumulator()
    for _ in range(SUBS):
        sub = np.full((64, 64), 500, dtype=np.uint16)
        sub[:8, :] = 65535
        acc.add(sub, 1.0)
    info = StackInfo(
        subs=acc.count, exposure=acc.exposure, start=datetime.now(UTC), full_scale=acc.full_scale
    )
    path = write_stack_fits(tmp_path / "stack.fits", acc.result(), info)
    assert fits_to_jpeg(path, tmp_path / "stack.jpg")["saturated_pct"] == 12.5


def test_the_imager_can_add_header_cards_without_touching_the_pixels(tmp_path: Path) -> None:
    path, pixels = _stack(tmp_path)
    _write_imagetyp(path, "dark")
    add_fits_header_cards(path, {"UNGUIDED": (1.5, "[s] unguided")})
    with astropy_fits.open(path, do_not_scale_image_data=True) as hdul:
        header = hdul[0].header
        assert header["BITPIX"] == 32 and header["IMAGETYP"] == "Dark Frame"
        assert header["UNGUIDED"] == 1.5 and header["EXPTIME"] == SUBS * 2.0
        assert header["SATURATE"] == SUBS * 65535
        assert (hdul[0].data == pixels).all()
