"""
Minimal FITS → JPEG preview.

Applies a percentile auto-stretch and saves a monochrome JPEG.
Colour cameras will show the raw Bayer pattern — good enough for
framing and focus checks. Full debayer is deferred (see TODO.md).
"""
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image


def fits_to_jpeg(fits_path: Path, jpeg_path: Path, quality: int = 85) -> None:
    with fits.open(fits_path) as hdul:
        data = hdul[0].data  # type: ignore[index]

    if data is None:
        raise ValueError(f"No image data in FITS file: {fits_path}")

    data = data.astype(np.float32)

    # Percentile auto-stretch: clip extreme values then scale to [0, 255]
    low, high = np.percentile(data, [1, 99])
    span = high - low
    if span < 1e-8:
        span = 1.0  # flat image guard
    stretched = np.clip((data - low) / span, 0.0, 1.0)
    uint8_data = (stretched * 255).astype(np.uint8)

    # astropy returns (height, width) for 2-D data; PIL expects the same
    Image.fromarray(uint8_data, mode="L").save(jpeg_path, format="JPEG", quality=quality)
