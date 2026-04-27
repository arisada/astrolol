"""Star detection and FWHM measurement using photutils.

Uses IRAFStarFinder which returns measured FWHM per source directly,
without requiring a separate PSF-fitting step.
"""
from __future__ import annotations

import asyncio
import structlog

logger = structlog.get_logger()


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
        logger.info(
            "autofocus.fits_info",
            n_hdus=len(hdul),
            hdu0_type=type(hdul[0]).__name__,
            hdu0_data_shape=getattr(hdul[0].data, "shape", None),
            hdu0_data_dtype=str(getattr(hdul[0].data, "dtype", None)),
        )
        data = hdul[0].data  # type: ignore[index]
        if data is None:
            logger.error("autofocus.detecting_stars.no_data", fits_path=fits_path)
            return 0.0, 0, []
        raw_dtype = str(data.dtype)
        raw_shape = data.shape
        raw_min = float(np.min(data))
        raw_max = float(np.max(data))
        data = data.astype(float)

    logger.info(
        "autofocus.fits_raw",
        dtype=raw_dtype,
        shape=raw_shape,
        raw_min=raw_min,
        raw_max=raw_max,
    )

    # Collapse multi-dimensional data (e.g. [1, H, W]) to 2D
    while data.ndim > 2:
        data = data[0]

    mean, median, std = sigma_clipped_stats(data, sigma=3.0)
    logger.info("autofocus.sigma_stats", mean=float(mean), median=float(median), std=float(std))

    if std <= 0:
        # sigma_clipped_stats clips star pixels as outliers when the background is
        # exactly 0 (e.g. CCD Simulator with no sky glow or read noise), leaving
        # only identical zeros → std=0.  Use 0.1 % of the data range as the
        # effective noise floor so IRAFStarFinder gets a meaningful threshold
        # (threshold = 5 * std ≈ 0.5 % of peak, which clears any zero background
        # and detects real PSF peaks).
        data_range = float(data.max() - data.min())
        if data_range <= 0:
            logger.error("autofocus.detecting_stars.flat_image", fits_path=fits_path)
            return 0.0, 0, []
        std = data_range * 0.001
        logger.info("autofocus.std_fallback", std=std, data_range=data_range)

    # Try progressively lower thresholds to handle faint stars or simulator images.
    sources = None
    for threshold_sigma in (5.0, 3.5, 2.5):
        finder = IRAFStarFinder(
            fwhm=3.0,
            threshold=threshold_sigma * std,
            sharpness_range=(0.2, 1.0),
            roundness_range=(-0.75, 0.75),
        )
        sources = finder(data - median)
        n = len(sources) if sources is not None else 0
        logger.info("autofocus.threshold_pass", sigma=threshold_sigma, n_sources=n)
        if sources is not None and len(sources) > 0:
            break

    if sources is None or len(sources) == 0:
        return 0.0, 0, []

    # Drop obviously non-stellar sources (very elongated or nearly-round but tiny)
    mask = np.abs(np.array(sources["roundness"], dtype=float)) < 0.75
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
            "x": float(s["x_centroid"]),
            "y": float(s["y_centroid"]),
            "fwhm": float(s["fwhm"]),
        }
        for s in sources
    ]
    return median_fwhm, len(stars), stars
