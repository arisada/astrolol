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


_MAX_HFD_STARS = 50      # cap on stars used for the expensive HFD bisection
_SUBSAMPLE = 2           # spatial subsampling factor applied before detection
_SUBSAMPLE_MIN_DIM = 900 # only subsample frames larger than this (longest side, px)
_MATCH_RADIUS = 8.0      # px, full-res — max centroid drift to still count as "the same star"


def _subsample_factor(shape: tuple[int, ...]) -> int:
    """Stride to apply before detection: _SUBSAMPLE on a large frame, 1 (no-op)
    on a small one. Purely a speed optimization, so it must scale with how large
    the frame actually is rather than applying a fixed stride unconditionally —
    see the call site in _detect_sync for why that matters for bin2+ frames.
    """
    return _SUBSAMPLE if max(shape) > _SUBSAMPLE_MIN_DIM else 1


def _sigma_clip_mask(values: "np.ndarray", sigma: float = 3.0, min_keep: int = 3) -> "np.ndarray":  # type: ignore[name-defined]
    """Boolean mask keeping values within *sigma* robust-sigma of the median.

    Uses the median absolute deviation (MAD) rather than the plain standard
    deviation to estimate spread. A plain std is not robust to the very
    outlier it's meant to catch: a single extreme value can inflate it enough
    that the outlier itself ends up within its own 3-sigma window (the
    classic "masking" failure of naive sigma-clipping on small samples).

    Returns an all-True mask when the MAD is 0 or clipping would drop below
    *min_keep* values — a handful of legitimate close values shouldn't be
    treated as all-outliers, and a degenerate (zero-spread) sample has
    nothing to clip anyway.
    """
    import numpy as np
    values = np.asarray(values, dtype=float)
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    if mad <= 0:
        return np.ones(len(values), dtype=bool)
    robust_sigma = 1.4826 * mad  # MAD -> std equivalent for a normal distribution
    mask = np.abs(values - med) < sigma * robust_sigma
    if mask.sum() < min_keep:
        return np.ones(len(values), dtype=bool)
    return mask


async def detect_stars(
    fits_path: str,
    metric: Metric = "fwhm",
    reference_stars: list[dict] | None = None,
) -> tuple[float, int, list[dict]]:
    """Detect stars in a FITS image and measure their sharpness.

    Returns ``(median_value, star_count, star_list)`` where each entry in
    ``star_list`` has ``x``, ``y``, ``fwhm`` keys (pixel coords; ``fwhm``
    always holds the FWHM regardless of metric, used for preview annotation).

    When *metric* is ``"hfd"``, the first return value is the median HFD
    across all detected stars instead of the median FWHM.

    *reference_stars*, when given, is a preferred set of stars (typically the
    result of a previous call, e.g. the first step of an autofocus sweep) to
    keep measuring the same population of stars step to step instead of
    whatever a fresh detection happens to threshold in on each time (adds
    variance unrelated to focus, since the detected population otherwise
    shifts frame to frame). Detection still runs fresh on every call — this
    only filters the result down to stars matched near a reference position,
    which is simpler and more robust than re-centroiding purely from the
    reference coordinates (it tolerates real star movement, e.g. mount
    drift, and still benefits from the full threshold-cascade detection).
    Reference stars with no nearby match this frame (e.g. spread below the
    detection floor once defocused) are simply dropped for this step. If
    *none* of them match, falls back to the full fresh detection rather than
    reporting zero stars.

    Returns ``(0.0, 0, [])`` when no stars are detected.
    Runs in a thread pool to avoid blocking the event loop.
    """
    return await asyncio.to_thread(_detect_sync, fits_path, metric, reference_stars)


def _match_reference_stars(
    stars: list[dict], reference_stars: list[dict], match_radius: float = _MATCH_RADIUS,
) -> list[dict]:
    """Greedily pair each reference star with its nearest current detection.

    Returns the subset of *stars* (this frame's freshly measured centroid/FWHM)
    that matched a reference star, one-to-one, within *match_radius* pixels.
    """
    available = list(stars)
    matched: list[dict] = []
    for ref in reference_stars:
        if not available:
            break
        best_i, best_d2 = None, match_radius ** 2
        for i, star in enumerate(available):
            d2 = (star["x"] - ref["x"]) ** 2 + (star["y"] - ref["y"]) ** 2
            if d2 <= best_d2:
                best_d2, best_i = d2, i
        if best_i is not None:
            matched.append(available.pop(best_i))
    return matched


def _compute_hfd(
    data: "np.ndarray", x: float, y: float, max_radius: float = 20.0, n_samples: int = 40,  # type: ignore[name-defined]
) -> float:
    """Return the Half-Flux Diameter for a star centred at (x, y).

    Samples the curve of growth (cumulative flux vs. aperture radius) up to
    *max_radius* and interpolates the radius at which it crosses 50 % of the
    total flux. Returns 0.0 if the total flux is non-positive.
    """
    import numpy as np
    from photutils.aperture import CircularAperture, aperture_photometry

    pos = [(x, y)]
    radii = np.linspace(0.5, max_radius, n_samples)
    fluxes = np.array([
        float(aperture_photometry(data, CircularAperture(pos, r=r))["aperture_sum"][0])
        for r in radii
    ])
    if fluxes[-1] <= 0:
        return 0.0

    # data is background-subtracted, so sky noise pixels are near-zero-mean but
    # can be negative, which makes individual samples of the curve of growth dip
    # below where they were at a smaller radius. The true (noise-free) curve is
    # monotonic, so a running maximum removes those dips. This is preferred over
    # clipping negative *pixels* to zero before summing: rectifying every noise
    # pixel gives the background a small but nonzero positive mean, and that
    # pedestal grows with the aperture's area (∝ r²) as the radius increases,
    # systematically inflating the result — worse the larger max_radius or the
    # fainter the star. A running maximum over the aggregate curve only
    # intervenes on actual downward dips, so it doesn't carry that bias.
    fluxes = np.maximum.accumulate(fluxes)
    total_flux = fluxes[-1]
    half = 0.5 * total_flux

    idx = int(np.searchsorted(fluxes, half))
    if idx <= 0:
        return 2.0 * float(radii[0])
    if idx >= len(radii):
        return 2.0 * float(radii[-1])
    r0, r1 = radii[idx - 1], radii[idx]
    f0, f1 = fluxes[idx - 1], fluxes[idx]
    frac = (half - f0) / (f1 - f0) if f1 > f0 else 0.0
    r_half = r0 + frac * (r1 - r0)
    return 2.0 * float(r_half)  # diameter


def _detect_sync(
    fits_path: str, metric: Metric = "fwhm", reference_stars: list[dict] | None = None,
) -> tuple[float, int, list[dict]]:
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
    # This is purely a speed optimization on a large frame, so it must be aware
    # of how large the frame actually is — applying a fixed stride unconditionally
    # double-dips with camera binning: a bin2 frame is already 1/4 the pixel count
    # of bin1, so striding it again leaves only 1/16 the points the sensor
    # actually captured. That starves the star centroid (and the FWHM estimate
    # used to size the HFD aperture, see _compute_hfd) of precision exactly when
    # the star's own pixel footprint is already smaller — hurting HFD (a discrete
    # aperture integral around that centroid) more than FWHM (a tolerant
    # parametric PSF fit).
    s = _subsample_factor(data.shape)
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
    good = _sigma_clip_mask(fwhms)
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

    if reference_stars:
        matched = _match_reference_stars(stars, reference_stars)
        if matched:
            logger.info(
                "autofocus.reference_stars_matched",
                reference=len(reference_stars), matched=len(matched), detected=len(stars),
            )
            stars = matched
            fwhms = np.array([star["fwhm"] for star in stars], dtype=float)
            median_fwhm = float(np.median(fwhms))
        else:
            logger.warning(
                "autofocus.reference_stars_lost",
                reference=len(reference_stars), detected=len(stars),
            )

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
            # A fixed 20px aperture for every star, however small, integrates a lot
            # of pure background noise once the sky is noisy — that inflates the
            # variance of the total-flux estimate the bisection searches against,
            # which occasionally sends one star's HFD far out on an unlucky frame
            # even though the growth curve is individually monotonic (the earlier
            # fix). Scaling the aperture to the star's own FWHM keeps it collecting
            # mostly star flux instead of noise, without starving genuinely
            # defocused (larger-PSF) stars of the radius they need.
            _compute_hfd(data - median, s_row["x"], s_row["y"], max_radius=max(8.0, min(40.0, s_row["fwhm"] * 4.0)))
            for s_row in hfd_stars
        ])
        valid_hfds = hfds[hfds > 0]
        if len(valid_hfds) == 0:
            return 0.0, 0, []

        # Sigma-clip outliers before the median, mirroring the FWHM clip above —
        # a single star's noise-driven bad HFD (or a hot pixel/cosmic ray it landed
        # near) shouldn't drag the whole step's reading, same reasoning as FWHM.
        valid_hfds = valid_hfds[_sigma_clip_mask(valid_hfds)]
        return float(np.median(valid_hfds)), len(stars), stars

    return median_fwhm, len(stars), stars
