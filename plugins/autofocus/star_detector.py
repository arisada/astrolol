"""Star detection and FWHM measurement using photutils.

Uses IRAFStarFinder which returns measured FWHM per source directly,
without requiring a separate PSF-fitting step.
"""
from __future__ import annotations

import asyncio


async def detect_stars(fits_path: str) -> tuple[float, int, list[dict]]:
    """Detect stars in a FITS image and measure their FWHM.

    Returns ``(median_fwhm_pixels, star_count, star_list)`` where each entry
    in ``star_list`` is a dict with ``x``, ``y``, ``fwhm`` keys (pixel coords).
    Returns ``(0.0, 0, [])`` when no stars are detected.

    Runs in a thread pool to avoid blocking the event loop.
    """
    return await asyncio.to_thread(_detect_sync, fits_path)


def _detect_sync(fits_path: str) -> tuple[float, int, list[dict]]:
    try:
        import numpy as np
        from astropy.io import fits
        from astropy.stats import sigma_clipped_stats
        from photutils.detection import IRAFStarFinder
    except ImportError as exc:
        raise RuntimeError(
            f"photutils is required for star detection. "
            f"Install it with: pip install photutils. Error: {exc}"
        ) from exc

    with fits.open(fits_path) as hdul:
        data = hdul[0].data  # type: ignore[index]
        if data is None:
            return 0.0, 0, []
        data = data.astype(float)

    # Collapse multi-dimensional data (e.g. [1, H, W]) to 2D
    while data.ndim > 2:
        data = data[0]

    mean, median, std = sigma_clipped_stats(data, sigma=3.0)

    if std <= 0:
        return 0.0, 0, []

    # seed fwhm=3px; threshold=5σ above background
    finder = IRAFStarFinder(fwhm=3.0, threshold=5.0 * std, sharplo=0.4, sharphi=0.9)
    sources = finder(data - median)

    if sources is None or len(sources) == 0:
        return 0.0, 0, []

    # Drop elongated sources (|roundness| > 0.5 indicates non-stellar or cosmic rays)
    mask = np.abs(np.array(sources["roundness"], dtype=float)) < 0.5
    sources = sources[mask]

    if len(sources) == 0:
        return 0.0, 0, []

    fwhms = np.array(sources["fwhm"], dtype=float)

    # Sigma-clip FWHM to remove remaining outliers before taking the median
    med = float(np.median(fwhms))
    sigma = float(np.std(fwhms))
    if sigma > 0:
        good = np.abs(fwhms - med) < 3.0 * sigma
        if good.sum() >= 3:
            sources = sources[good]
            fwhms = fwhms[good]

    median_fwhm = float(np.median(fwhms))
    stars = [
        {
            "x": float(s["xcentroid"]),
            "y": float(s["ycentroid"]),
            "fwhm": float(s["fwhm"]),
        }
        for s in sources
    ]
    return median_fwhm, len(stars), stars
