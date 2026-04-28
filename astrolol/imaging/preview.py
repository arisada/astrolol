"""
FITS → JPEG preview generators.

Two stretching modes:
- Auto: resize to preview dimensions, then median black-point + 99th-percentile
  white-point stretch.  The sky background (below the median) maps to black,
  hiding noise while preserving nebulosity and stars above the background level.
- Linear (min-max): scales the full data range to [0, 255] with no clipping.
  Useful for bright objects and sanity-checking raw data.

Both modes downscale to at most _PREVIEW_MAX_DIM on the longest side before
any per-pixel work, so JPEG encoding, stretching, and uint8 conversion all
operate on the smaller array.

Colour cameras will show the raw Bayer pattern — good enough for framing and
focus checks. Full debayer is deferred (see TODO.md).
"""
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image

_PREVIEW_MAX_DIM = 2000


def _load_fits_data(fits_path: Path) -> np.ndarray:
    with fits.open(fits_path) as hdul:
        data = hdul[0].data  # type: ignore[index]
    if data is None:
        raise ValueError(f"No image data in FITS file: {fits_path}")
    return data.astype(np.float32)


def _resize_for_preview(data: np.ndarray) -> np.ndarray:
    """Downscale so the longest side is at most _PREVIEW_MAX_DIM, preserving ratio.

    Uses PIL LANCZOS (sinc-based) resampling on a float32 mode-F image so the
    resize is smooth and the dynamic range of the original data is preserved.
    Returns data unchanged when it already fits within the limit.
    """
    h, w = data.shape
    if h <= _PREVIEW_MAX_DIM and w <= _PREVIEW_MAX_DIM:
        return data
    scale = _PREVIEW_MAX_DIM / max(h, w)
    new_w = max(1, round(w * scale))
    new_h = max(1, round(h * scale))
    return np.asarray(Image.fromarray(data, mode="F").resize((new_w, new_h), Image.LANCZOS))


def fits_to_jpeg(fits_path: Path, jpeg_path: Path, quality: int = 85) -> dict:
    """Auto-stretch: median black-point + 99th-percentile white-point.

    Returns a stats dict with histogram and stretch parameters so the caller can
    build an ``ImageStats`` without re-reading the file.
    """
    data = _resize_for_preview(_load_fits_data(fits_path))
    # Sample every 63rd pixel — stride 63 (not a power of 2) avoids landing on
    # the same Bayer colour channel repeatedly.  After resize a 2000×2000 image
    # yields ~63 K sample points, enough for a stable percentile estimate.
    sample = data.ravel()[::63]
    low = float(np.median(sample))
    high = float(np.percentile(sample, 99))
    span = high - low
    if span < 1e-8:
        span = 1.0
    stretched = np.clip((data - low) / span, 0.0, 1.0)
    uint8_data = (stretched * 255).astype(np.uint8)
    Image.fromarray(uint8_data, mode="L").save(jpeg_path, format="JPEG", quality=quality)

    s_min = float(sample.min())
    s_max = float(sample.max()) if sample.max() > s_min else s_min + 1.0
    hist, _ = np.histogram(sample, bins=128, range=(s_min, s_max))
    return {
        "histogram": hist.tolist(),
        "hist_min": s_min,
        "hist_max": s_max,
        "stretch_low": low,
        "stretch_high": high,
        "mean": float(np.mean(sample)),
        "median": low,
    }


def fits_to_jpeg_linear(fits_path: Path, jpeg_path: Path, quality: int = 85) -> None:
    """Linear stretch: scale data from min to max with no clipping."""
    data = _resize_for_preview(_load_fits_data(fits_path))
    low, high = float(data.min()), float(data.max())
    span = high - low
    if span < 1e-8:
        span = 1.0
    stretched = (data - low) / span
    uint8_data = (stretched * 255).astype(np.uint8)
    Image.fromarray(uint8_data, mode="L").save(jpeg_path, format="JPEG", quality=quality)
