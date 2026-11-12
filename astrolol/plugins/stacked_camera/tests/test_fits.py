"""Tests for writing a stack as FITS."""
from __future__ import annotations

from datetime import UTC, datetime, timezone
from pathlib import Path

import astropy.io.fits as astropy_fits
import numpy as np

from astrolol.plugins.stacked_camera.fits import StackInfo, write_stack_fits


def _info(**overrides: object) -> StackInfo:
    start = datetime(2026, 11, 12, 21, 30, 5, 250000, tzinfo=UTC)
    values: dict[str, object] = dict(subs=300, exposure=300.0, start=start)
    values.update(overrides)
    return StackInfo(**values)  # type: ignore[arg-type]


def test_roundtrip_keeps_int32_pixels(tmp_path: Path) -> None:
    pixels = np.arange(24, dtype=np.int32).reshape(4, 6) * 70_000  # beyond 16 bits
    path = write_stack_fits(tmp_path / "stack.fits", pixels, _info())
    with astropy_fits.open(path, do_not_scale_image_data=True) as hdul:
        assert hdul[0].header["BITPIX"] == 32
        assert "BZERO" not in hdul[0].header  # raw values, no scaling to undo
        assert (hdul[0].data == pixels).all()


def test_header_describes_the_stack(tmp_path: Path) -> None:
    path = write_stack_fits(
        tmp_path / "stack.fits",
        np.zeros((2, 2), dtype=np.int32),
        _info(gain=120, binning=2, temperature=-10.5, dropped=3),
    )
    h = astropy_fits.getheader(path)
    assert h["EXPTIME"] == 300.0
    assert h["EXPOSURE"] == 300.0
    assert h["NSUBS"] == 300
    assert h["SUBEXP"] == 1.0
    assert h["NDROP"] == 3
    assert h["GAIN"] == 120
    assert h["XBINNING"] == h["YBINNING"] == 2
    assert h["CCD-TEMP"] == -10.5
    assert h["DATE-OBS"] == "2026-11-12T21:30:05.250000"
    assert h["STACKMD"] == "sum"
    assert "OFFSET" not in h and "PEDESTAL" not in h  # nothing was subtracted


def test_optional_cards_are_left_out_when_unknown(tmp_path: Path) -> None:
    path = write_stack_fits(tmp_path / "stack.fits", np.zeros((2, 2), dtype=np.int32), _info())
    h = astropy_fits.getheader(path)
    assert "GAIN" not in h and "CCD-TEMP" not in h


def test_extra_cards_from_the_camera(tmp_path: Path) -> None:
    path = write_stack_fits(
        tmp_path / "stack.fits",
        np.zeros((2, 2), dtype=np.int32),
        _info(extra={"BAYERPAT": ("RGGB", "Bayer pattern")}),
    )
    assert astropy_fits.getheader(path)["BAYERPAT"] == "RGGB"


def test_a_naive_start_time_is_taken_as_utc(tmp_path: Path) -> None:
    path = write_stack_fits(
        tmp_path / "stack.fits",
        np.zeros((2, 2), dtype=np.int32),
        _info(start=datetime(2026, 11, 12, 21, 30, 5)),
    )
    assert astropy_fits.getheader(path)["DATE-OBS"].startswith("2026-11-12T21:30:05")


def test_a_zone_aware_start_is_converted_to_utc(tmp_path: Path) -> None:
    from datetime import timedelta

    paris = timezone(timedelta(hours=1))
    path = write_stack_fits(
        tmp_path / "stack.fits",
        np.zeros((2, 2), dtype=np.int32),
        _info(start=datetime(2026, 11, 12, 22, 30, 5, tzinfo=paris)),
    )
    assert astropy_fits.getheader(path)["DATE-OBS"].startswith("2026-11-12T21:30:05")


def test_leaves_only_the_final_file(tmp_path: Path) -> None:
    write_stack_fits(tmp_path / "stack.fits", np.zeros((2, 2), dtype=np.int32), _info())
    assert [p.name for p in tmp_path.iterdir()] == ["stack.fits"]


def test_overwrites_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "stack.fits"
    write_stack_fits(path, np.zeros((2, 2), dtype=np.int32), _info())
    write_stack_fits(path, np.ones((2, 2), dtype=np.int32), _info())
    assert (astropy_fits.getdata(path) == 1).all()


def test_saturate_tells_the_full_scale_of_the_sum(tmp_path: Path) -> None:
    path = write_stack_fits(
        tmp_path / "stack.fits", np.zeros((2, 2), dtype=np.int32), _info(full_scale=20 * 65535)
    )
    assert astropy_fits.getheader(path)["SATURATE"] == 20 * 65535


def test_no_saturate_card_without_a_full_scale(tmp_path: Path) -> None:
    path = write_stack_fits(tmp_path / "stack.fits", np.zeros((2, 2), dtype=np.int32), _info())
    assert "SATURATE" not in astropy_fits.getheader(path)
