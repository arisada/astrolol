"""Lightweight per-frame quality metrics (light frames only): background level, star
count, and a rough HFR-style sharpness figure — good enough to sort by for "find the
outlier among 180 near-identical subs", not focus-critical precision.

Deliberately simpler than the autofocus plugin's star detector (subsampling, reference-
star matching, HFD bisection): plugins can't import each other's code, and this only
needs approximate numbers, not autofocus-grade accuracy. If the two ever want to share
more, that goes through the event bus, not a direct import.

Runs on a background, low-priority queue (see ``QualityWorker`` in ``plugin.py``),
decoupled from indexing and thumbnail generation — it never competes with an active
capture session for CPU.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

logger = structlog.get_logger()

_MAX_ANALYSIS_DIM = 800  # downsample larger frames before detection — speed, not precision


async def compute_quality(fits_path: Path) -> tuple[float | None, int | None, float | None]:
    """Returns (background_median, star_count, hfr). All None/0 on failure or a frame
    with no image data — never raises."""
    return await asyncio.to_thread(_compute_sync, fits_path)


def _compute_sync(fits_path: Path) -> tuple[float | None, int | None, float | None]:
    try:
        import numpy as np
        from astropy.io import fits
        from astropy.stats import sigma_clipped_stats
        from photutils.detection import IRAFStarFinder

        with fits.open(fits_path) as hdul:
            data = hdul[0].data
        if data is None:
            return None, None, None
        data = data.astype(np.float32)
        data = _subsample(data, _MAX_ANALYSIS_DIM)

        _, median, std = sigma_clipped_stats(data, sigma=3.0)
        if std <= 0:
            return float(median), 0, None

        finder = IRAFStarFinder(threshold=float(median + 5 * std), fwhm=4.0, minsep_fwhm=3.0)
        sources = finder(data - median)
        if sources is None or len(sources) == 0:
            return float(median), 0, None

        fwhms = np.asarray(sources["fwhm"], dtype=float)
        fwhms = fwhms[np.isfinite(fwhms) & (fwhms > 0)]
        hfr = float(np.median(fwhms)) / 2.0 if len(fwhms) else None
        return float(median), int(len(sources)), hfr
    except Exception as exc:
        logger.warning("viewer.quality_analysis_failed", path=str(fits_path), error=str(exc))
        return None, None, None


def _subsample(data: "np.ndarray", max_dim: int) -> "np.ndarray":  # type: ignore[name-defined]
    h, w = data.shape[:2]
    if max(h, w) <= max_dim:
        return data
    stride = max(1, round(max(h, w) / max_dim))
    return data[::stride, ::stride]
