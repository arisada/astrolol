"""Writing a finished stack as a FITS file the imager can pick up like any camera's frame."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import astropy.io.fits as astropy_fits
import numpy as np

SOFTWARE = "astrolol stacked_camera"


@dataclass(frozen=True)
class StackInfo:
    """What the header says about how the stack was made."""

    subs: int  # sub-exposures added
    exposure: float  # seconds of light: the sum of the subs' lengths
    start: datetime  # when the first sub started
    gain: int | None = None
    binning: int = 1
    temperature: float | None = None
    dropped: int = 0  # subs the camera delivered but the stack could not take
    full_scale: int | None = None  # ADU of a pixel that was saturated in every sub
    # Header cards the camera knows about (Bayer pattern, ...): keyword -> (value, comment)
    extra: dict[str, tuple[object, str]] = field(default_factory=dict)


def write_stack_fits(path: str | Path, pixels: np.ndarray, info: StackInfo) -> Path:
    """Write *pixels* (the raw int32 sum) to *path*; returns the path.

    The file appears under its final name only once complete, because the imager reads it as
    soon as the exposure returns.
    """
    path = Path(path)
    hdu = astropy_fits.PrimaryHDU(np.ascontiguousarray(pixels))
    header = hdu.header
    start = info.start if info.start.tzinfo else info.start.replace(tzinfo=UTC)
    header["EXPTIME"] = (info.exposure, "[s] light in the stack, the sum of the subs")
    header["EXPOSURE"] = (info.exposure, "[s] same as EXPTIME")
    date_obs = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")
    header["DATE-OBS"] = (date_obs, "UTC, start of the first sub")
    header["XBINNING"] = (info.binning, "")
    header["YBINNING"] = (info.binning, "")
    if info.gain is not None:
        header["GAIN"] = (info.gain, "")
    if info.temperature is not None:
        header["CCD-TEMP"] = (info.temperature, "[C] sensor temperature at the end")
    header["NSUBS"] = (info.subs, "sub-exposures in the stack")
    header["SUBEXP"] = (info.exposure / info.subs if info.subs else 0.0, "[s] mean sub-exposure")
    header["NDROP"] = (info.dropped, "subs lost before they could be added")
    if info.full_scale:
        header["SATURATE"] = (info.full_scale, "[ADU] a pixel saturated in every sub")
    header["STACKMD"] = ("sum", "raw sum of the subs, nothing subtracted")
    header["SWCREATE"] = (SOFTWARE, "")
    for key, (value, comment) in info.extra.items():
        header[key] = (value, comment)

    part = path.with_name(path.name + ".part")
    try:
        hdu.writeto(part, overwrite=True, output_verify="silentfix")
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
    return path
