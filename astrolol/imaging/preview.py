"""
FITS → JPEG preview generators.

Two stretching modes:
- Auto (percentile): clips the bottom 1% and top 1% of pixel values, then
  scales to [0, 255]. Good for nebulae and faint extended objects.
- Linear (min-max): scales the full data range to [0, 255] with no clipping.
  Useful for bright objects and sanity-checking raw data.

Colour cameras will show the raw Bayer pattern — good enough for framing and
focus checks. Full debayer is deferred (see TODO.md).
"""
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image


def _load_fits_data(fits_path: Path) -> np.ndarray:
    with fits.open(fits_path) as hdul:
        data = hdul[0].data  # type: ignore[index]
    if data is None:
        raise ValueError(f"No image data in FITS file: {fits_path}")
    return data.astype(np.float32)


def fits_to_jpeg(fits_path: Path, jpeg_path: Path, quality: int = 85) -> None:
    """Auto-stretch: percentile [1, 99] clip then scale to [0, 255]."""
    data = _load_fits_data(fits_path)
    low, high = np.percentile(data, [1, 99])
    span = high - low
    if span < 1e-8:
        span = 1.0
    stretched = np.clip((data - low) / span, 0.0, 1.0)
    uint8_data = (stretched * 255).astype(np.uint8)
    Image.fromarray(uint8_data, mode="L").save(jpeg_path, format="JPEG", quality=quality)


def fits_to_jpeg_linear(fits_path: Path, jpeg_path: Path, quality: int = 85) -> None:
    """Linear stretch: scale data from min to max with no clipping."""
    data = _load_fits_data(fits_path)
    low, high = float(data.min()), float(data.max())
    span = high - low
    if span < 1e-8:
        span = 1.0
    stretched = (data - low) / span
    uint8_data = (stretched * 255).astype(np.uint8)
    Image.fromarray(uint8_data, mode="L").save(jpeg_path, format="JPEG", quality=quality)
