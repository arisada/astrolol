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


def _load_fits_data(fits_path: Path) -> tuple[np.ndarray, float]:
    """Load FITS pixel data plus the sensor's theoretical full-scale ADU value.

    The full-scale value comes from the on-disk integer dtype (e.g. 65535 for
    uint16, 255 for uint8) — the same convention imaging software like N.I.N.A.
    uses to judge clipping. It is read *before* the cast to float32 below, since
    that cast would otherwise erase the original dtype. Float FITS data (rare)
    has no fixed full-scale value, so its own max is used instead.
    """
    with fits.open(fits_path) as hdul:
        data = hdul[0].data  # type: ignore[index]
    if data is None:
        raise ValueError(f"No image data in FITS file: {fits_path}")
    if np.issubdtype(data.dtype, np.integer):
        adu_max = float(np.iinfo(data.dtype).max)
    else:
        adu_max = float(data.max())
    return data.astype(np.float32), adu_max


def _resize_for_preview(data: np.ndarray, max_dim: int = _PREVIEW_MAX_DIM) -> np.ndarray:
    """Downscale so the longest side is at most *max_dim*, preserving ratio.

    Uses PIL LANCZOS (sinc-based) resampling on a float32 mode-F image so the
    resize is smooth and the dynamic range of the original data is preserved.
    Returns data unchanged when it already fits within the limit.
    """
    h, w = data.shape
    if h <= max_dim and w <= max_dim:
        return data
    scale = max_dim / max(h, w)
    new_w = max(1, round(w * scale))
    new_h = max(1, round(h * scale))
    return np.asarray(Image.fromarray(data, mode="F").resize((new_w, new_h), Image.LANCZOS))


def fits_to_jpeg(
    fits_path: Path,
    jpeg_path: Path,
    quality: int = 85,
    black_percentile: float = 50.0,
    white_percentile: float = 99.0,
) -> dict:
    """Auto-stretch: configurable black-point / white-point percentile stretch.

    Defaults (50th / 99th percentile) match the historical median + 99th-percentile
    behaviour; callers can widen the percentiles to produce a gentler stretch.

    Returns a stats dict with histogram and stretch parameters so the caller can
    build an ``ImageStats`` without re-reading the file.
    """
    data, adu_max = _load_fits_data(fits_path)
    data = _resize_for_preview(data)
    # Sample every 63rd pixel — stride 63 (not a power of 2) avoids landing on
    # the same Bayer colour channel repeatedly.  After resize a 2000×2000 image
    # yields ~63 K sample points, enough for a stable percentile estimate.
    sample = data.ravel()[::63]
    low = float(np.percentile(sample, black_percentile))
    high = float(np.percentile(sample, white_percentile))
    span = high - low
    if span < 1e-8:
        span = 1.0
    stretched = np.clip((data - low) / span, 0.0, 1.0)
    uint8_data = (stretched * 255).astype(np.uint8)
    Image.fromarray(uint8_data, mode="L").save(jpeg_path, format="JPEG", quality=quality)

    # Histogram is binned over the sensor's full-scale range (not the sample's own
    # min/max) so clipped highlights show as a spike at the true right edge and the
    # shot's exposure level can be judged at a glance, instead of the axis silently
    # rescaling to whatever this particular frame's brightest/darkest pixel was.
    hist_min = 0.0
    hist_max = adu_max if adu_max > hist_min else float(sample.max()) or 1.0
    hist, _ = np.histogram(sample, bins=128, range=(hist_min, hist_max))
    return {
        "histogram": hist.tolist(),
        "hist_min": hist_min,
        "hist_max": hist_max,
        "stretch_low": low,
        "stretch_high": high,
        "mean": float(np.mean(sample)),
        "median": float(np.median(sample)),
    }


def fits_to_jpeg_linear(fits_path: Path, jpeg_path: Path, quality: int = 85) -> None:
    """Linear stretch: scale data from min to max with no clipping."""
    data, _ = _load_fits_data(fits_path)
    data = _resize_for_preview(data)
    low, high = float(data.min()), float(data.max())
    span = high - low
    if span < 1e-8:
        span = 1.0
    stretched = (data - low) / span
    uint8_data = (stretched * 255).astype(np.uint8)
    Image.fromarray(uint8_data, mode="L").save(jpeg_path, format="JPEG", quality=quality)


def fits_to_thumbnail(fits_path: Path, jpeg_path: Path, max_dim: int = 256, quality: int = 70) -> None:
    """Small, fixed-stretch preview for a library grid/list — never re-adjustable.

    Uses the same default 50th/99th percentile auto-stretch as ``fits_to_jpeg`` but at
    a much smaller size, so generating thousands of these (an imported library) is cheap
    relative to full-resolution previews.
    """
    data, _ = _load_fits_data(fits_path)
    data = _resize_for_preview(data, max_dim=max_dim)
    sample = data.ravel()[::63] if data.size > 63 else data.ravel()
    low = float(np.percentile(sample, 50.0))
    high = float(np.percentile(sample, 99.0))
    span = high - low
    if span < 1e-8:
        span = 1.0
    stretched = np.clip((data - low) / span, 0.0, 1.0)
    uint8_data = (stretched * 255).astype(np.uint8)
    Image.fromarray(uint8_data, mode="L").save(jpeg_path, format="JPEG", quality=quality)
