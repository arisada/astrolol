"""Star detection and FWHM / HFD measurement using photutils.

Uses IRAFStarFinder which returns measured FWHM per source directly,
without requiring a separate PSF-fitting step.  When metric="hfd" the
returned value is the Half-Flux Diameter computed via a growing circular
aperture (the aperture radius at which 50 % of the total enclosed flux
is reached, doubled).
"""
from __future__ import annotations

import asyncio
import structlog

logger = structlog.get_logger()

Metric = str  # "fwhm" | "hfd"


_MAX_HFD_STARS = 50   # cap on stars used for the expensive HFD bisection
_SUBSAMPLE = 2        # spatial subsampling factor applied before detection


async def detect_stars(fits_path: str, metric: Metric = "fwhm") -> tuple[float, int, list[dict]]:
    """Detect stars in a FITS image and measure their sharpness.

    Returns ``(median_value, star_count, star_list)`` where each entry in
    ``star_list`` has ``x``, ``y``, ``fwhm`` keys (pixel coords; ``fwhm``
    always holds the FWHM regardless of metric, used for preview annotation).

    When *metric* is ``"hfd"``, the first return value is the median HFD
    across all detected stars instead of the median FWHM.

    Returns ``(0.0, 0, [])`` when no stars are detected.
    Runs in a thread pool to avoid blocking the event loop.
    """
    return await asyncio.to_thread(_detect_sync, fits_path, metric)


def _compute_hfd(data: "np.ndarray", x: float, y: float, max_radius: float = 20.0) -> float:  # type: ignore[name-defined]
    """Return the Half-Flux Diameter for a star centred at (x, y).

    Grows a circular aperture until it encloses 50 % of the total flux
    measured within *max_radius*.  Returns 0.0 if the flux is non-positive.
    """
    import numpy as np
    from photutils.aperture import CircularAperture, aperture_photometry

    pos = [(x, y)]
    total_ap = CircularAperture(pos, r=max_radius)
    total_flux = float(aperture_photometry(data, total_ap)["aperture_sum"][0])
    if total_flux <= 0:
        return 0.0

    half = 0.5 * total_flux
    lo, hi = 0.5, max_radius
    for _ in range(20):  # bisection — 20 iterations → < 0.002 px error
        mid = (lo + hi) / 2.0
        ap = CircularAperture(pos, r=mid)
        flux = float(aperture_photometry(data, ap)["aperture_sum"][0])
        if flux < half:
            lo = mid
        else:
            hi = mid
    return 2.0 * ((lo + hi) / 2.0)  # diameter


def _detect_sync(fits_path: str, metric: Metric = "fwhm") -> tuple[float, int, list[dict]]:
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
        # Convert and subsample in one step to minimise peak memory.
        # Strided slicing creates a view, astype forces a copy at reduced size.
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

    # Subsample spatially to reduce compute for sigma stats and star finding.
    # Coordinates are scaled back to full-res below when building star_list.
    s = _SUBSAMPLE
    data_s = data[::s, ::s]

    mean, median, std = sigma_clipped_stats(data_s, sigma=3.0)
    logger.info("autofocus.sigma_stats", mean=float(mean), median=float(median), std=float(std))

    if std <= 0:
        # sigma_clipped_stats clips star pixels as outliers when the background is
        # exactly 0 (e.g. CCD Simulator with no sky glow or read noise), leaving
        # only identical zeros → std=0.  Use 0.1 % of the data range as the
        # effective noise floor so IRAFStarFinder gets a meaningful threshold
        # (threshold = 5 * std ≈ 0.5 % of peak, which clears any zero background
        # and detects real PSF peaks).
        data_range = float(data_s.max() - data_s.min())
        if data_range <= 0:
            logger.error("autofocus.detecting_stars.flat_image", fits_path=fits_path)
            return 0.0, 0, []
        std = data_range * 0.001
        logger.info("autofocus.std_fallback", std=std, data_range=data_range)

    # Try progressively lower thresholds to handle faint stars or simulator images.
    # fwhm is halved because the subsampled pixel scale is s× coarser.
    sources = None
    for threshold_sigma in (5.0, 3.5, 2.5):
        finder = IRAFStarFinder(
            fwhm=max(1.5, 3.0 / s),
            threshold=threshold_sigma * std,
            sharpness_range=(0.2, 1.0),
            roundness_range=(-0.75, 0.75),
        )
        sources = finder(data_s - median)
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

    fwhms = np.array(sources["fwhm"], dtype=float) * s  # scale back to full-res pixels

    # Sigma-clip FWHM to remove remaining outliers before taking the median
    med = float(np.median(fwhms))
    sigma = float(np.std(fwhms))
    if sigma > 0:
        good = np.abs(fwhms - med) < 3.0 * sigma
        if good.sum() >= 3:
            sources = sources[good]
            fwhms = fwhms[good]

    median_fwhm = float(np.median(fwhms))

    # Scale subsampled centroids back to full-resolution pixel coordinates.
    stars = [
        {
            "x": float(s_row["x_centroid"]) * s,
            "y": float(s_row["y_centroid"]) * s,
            "fwhm": float(s_row["fwhm"]) * s,
        }
        for s_row in sources
    ]

    if metric == "hfd":
        # Select stars closest to the median FWHM for HFD measurement.
        # Sorting by proximity to median avoids hot pixels (FWHM << median)
        # and saturated/bloomed stars (FWHM >> median), which both give
        # unreliable HFD values. Peak-flux sorting is explicitly avoided
        # because hot pixels have high peak but negligible total flux.
        dist_from_median = np.abs(fwhms - median_fwhm)
        order = np.argsort(dist_from_median)
        hfd_stars = [stars[i] for i in order[:_MAX_HFD_STARS]]
        logger.info("autofocus.hfd_sample", total_stars=len(stars), hfd_sample=len(hfd_stars))
        hfds = np.array([
            _compute_hfd(data - median, s_row["x"], s_row["y"])
            for s_row in hfd_stars
        ])
        valid_hfds = hfds[hfds > 0]
        if len(valid_hfds) == 0:
            return 0.0, 0, []
        return float(np.median(valid_hfds)), len(stars), stars

    return median_fwhm, len(stars), stars
