"""Star detection and FWHM / HFD measurement for autofocus.

Autofocus has to measure stars from sharp to very defocused, so detection cannot
assume a star size. Stars are found by scale-space blob detection: the frame is
filtered with normalised Laplacian-of-Gaussian kernels of increasing size and a
star is a peak over position *and* size, so a 2 px star and a 40 px blob are
both found at the kernel that matches them. Each star is then measured on a
local stamp (local background, windowed-moment FWHM, half-flux diameter).

Isolated hot pixels are removed before anything else, since a single hot pixel
keeps its full peak at any focus position and would otherwise be the one thing
detected on a badly defocused frame.
"""
from __future__ import annotations

import asyncio
import structlog

logger = structlog.get_logger()

Metric = str  # "fwhm" | "hfd"


# Kernel sigmas (px, full resolution) searched for stars, ~x1.5 apart: from an
# undersampled in-focus star (FWHM ~2.4 px) to a heavily defocused one (~90 px).
_SCALES = (1.0, 1.5, 2.25, 3.4, 5.1, 7.6, 11.4, 17.1, 25.6, 38.4)
_DETECT_SIGMA = 6.0      # peak significance (in robust noise sigmas) to accept a blob
_MAX_CANDIDATES = 400    # strongest candidates kept for de-duplication
_MAX_STARS = 150         # cap on stars measured per frame
_HOT_SIGMA = 5.0         # a pixel this far above its neighbours' median may be hot...
_HOT_COMPACT = 0.12      # ...if its brightest neighbour is under this fraction of its height above the sky
_MAX_PEAK_FRACTION = 0.7 # a source with more of its flux than this in one pixel is a hot pixel, not a star
_MAX_ELLIPTICITY = 0.6   # trails, cosmic-ray tracks and blended pairs are not focus targets
_MATCH_RADIUS = 8.0      # px, full-res — max centroid drift to still count as "the same star"


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
    whatever a fresh detection happens to find each time (adds variance
    unrelated to focus, since the detected population otherwise shifts frame to
    frame). Detection still runs fresh on every call — this only filters the
    result down to stars matched near a reference position, which tolerates real
    star movement (e.g. mount drift). Reference stars with no nearby match this
    frame are dropped for this step. If *none* of them match, the step reports
    no stars rather than measuring an unrelated population.

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
    data: "np.ndarray", x: float, y: float, max_radius: float = 20.0,  # type: ignore[name-defined]
) -> float:
    """Return the Half-Flux Diameter for a star centred at (x, y).

    Builds the curve of growth (cumulative flux vs. distance from the centre,
    one sample per pixel) up to *max_radius* and interpolates the radius at
    which it crosses 50 % of the total flux. Returns 0.0 if the total flux is
    non-positive.
    """
    import numpy as np

    h, w = data.shape
    x0, x1 = max(0, int(np.floor(x - max_radius))), min(w, int(np.ceil(x + max_radius)) + 1)
    y0, y1 = max(0, int(np.floor(y - max_radius))), min(h, int(np.ceil(y + max_radius)) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    r = np.hypot(xx - x, yy - y).ravel()
    flux = data[y0:y1, x0:x1].ravel()
    inside = r <= max_radius
    r, flux = r[inside], flux[inside]
    if r.size == 0:
        return 0.0
    order = np.argsort(r, kind="stable")
    radii = r[order]
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
    fluxes = np.maximum.accumulate(np.cumsum(flux[order]))
    total_flux = fluxes[-1]
    if total_flux <= 0:
        return 0.0
    half = 0.5 * total_flux

    idx = int(np.searchsorted(fluxes, half))
    if idx <= 0:
        return 2.0 * float(radii[0])
    r0, r1 = radii[idx - 1], radii[idx]
    f0, f1 = fluxes[idx - 1], fluxes[idx]
    frac = (half - f0) / (f1 - f0) if f1 > f0 else 0.0
    return 2.0 * float(r0 + frac * (r1 - r0))  # diameter


def _bin_mean(data: "np.ndarray", b: int) -> "np.ndarray":  # type: ignore[name-defined]
    """Average *b*×*b* blocks (trailing rows/columns that don't fill a block are dropped)."""
    h, w = (data.shape[0] // b) * b, (data.shape[1] // b) * b
    return data[:h, :w].reshape(h // b, b, w // b, b).mean(axis=(1, 3))


def _robust_noise(values: "np.ndarray") -> float:  # type: ignore[name-defined]
    import numpy as np
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


def _suppress_hot_pixels(data: "np.ndarray") -> tuple["np.ndarray", int]:  # type: ignore[name-defined]
    """Replace isolated single-pixel spikes by the median of their neighbours.

    A hot pixel rises far above the local sky *without* lifting its neighbours;
    even an undersampled star (FWHM ~1.5 px) lights up the pixels next to its
    peak. So a pixel is hot when it is well above its neighbours and its brightest
    neighbour carries only a small fraction of its height above the sky, the sky
    being taken one ring further out (outside any star's core). Returns the
    cleaned copy and the number of pixels replaced.
    """
    import numpy as np
    from scipy import ndimage as ndi

    near = np.ones((3, 3), dtype=bool)
    near[1, 1] = False
    neighbour_median = ndi.median_filter(data, footprint=near, mode="nearest")
    excess = data - neighbour_median
    noise = _robust_noise(excess)
    if noise <= 0:
        noise = max(1e-6, 1e-3 * float(np.ptp(data)))
    ys, xs = np.nonzero(excess > _HOT_SIGMA * noise)
    if ys.size == 0:
        return data, 0

    # Only the few spiking pixels need the (expensive) sky / brightest-neighbour test.
    padded = np.pad(data, 2, mode="edge")
    ring1 = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]
    ring2 = [(dy, dx) for dy in range(-2, 3) for dx in range(-2, 3) if max(abs(dy), abs(dx)) == 2]
    neighbour_max = np.max([padded[ys + 2 + dy, xs + 2 + dx] for dy, dx in ring1], axis=0)
    sky = np.median([padded[ys + 2 + dy, xs + 2 + dx] for dy, dx in ring2], axis=0)
    is_hot = (neighbour_max - sky) < _HOT_COMPACT * (data[ys, xs] - sky)
    if not is_hot.any():
        return data, 0
    cleaned = data.copy()
    cleaned[ys[is_hot], xs[is_hot]] = neighbour_median[ys[is_hot], xs[is_hot]]
    return cleaned, int(is_hot.sum())


def _find_blobs(data: "np.ndarray") -> list[tuple[float, float, float, float]]:  # type: ignore[name-defined]
    """Scale-space blob detection. Returns ``(x, y, sigma, significance)`` strongest first.

    Each kernel size is a matched filter for stars of that size, so a star is
    found at the scale where its significance peaks — wide, dim defocused stars
    that a fixed small kernel buries in the noise stand out at a larger kernel.
    Large kernels run on block-averaged copies of the frame (cheap, and the
    averaging is where the signal-to-noise comes from anyway).
    """
    import numpy as np
    from scipy import ndimage as ndi

    candidates: list[tuple[float, float, float, float]] = []
    for sigma in _SCALES:
        b = 1
        while b * 2 <= sigma / 1.5:
            b *= 2
        img = _bin_mean(data, b) if b > 1 else data
        s = sigma / b
        # Scale-normalised, sign-flipped LoG: positive on bright blobs of size ~sigma.
        response = -ndi.gaussian_laplace(img, s, mode="reflect") * s * s
        centre = float(np.median(response))
        noise = _robust_noise(response)
        if noise <= 0:  # noiseless frame (e.g. a synthetic image): fall back to the dynamic range
            noise = max(1e-9, 1e-3 * float(np.ptp(response)))
        z = (response - centre) / noise
        r = max(2, int(round(1.5 * s)))
        peaks = (z == ndi.maximum_filter(z, size=2 * r + 1)) & (z > _DETECT_SIGMA)
        ys, xs = np.nonzero(peaks)
        # A star whose 3-sigma disc leaves the frame can't be measured faithfully.
        margin = int(np.ceil(3.0 * s))
        inside = (xs >= margin) & (xs < img.shape[1] - margin) & (ys >= margin) & (ys < img.shape[0] - margin)
        for x, y in zip(xs[inside], ys[inside]):
            candidates.append((x * b + (b - 1) / 2, y * b + (b - 1) / 2, sigma, float(z[y, x])))

    # The same star is a peak at several neighbouring scales: keep the most
    # significant, drop anything inside its footprint.
    candidates.sort(key=lambda c: -c[3])
    accepted: list[tuple[float, float, float, float]] = []
    for cand in candidates[:_MAX_CANDIDATES]:
        cx, cy, cs, _ = cand
        if all((cx - ax) ** 2 + (cy - ay) ** 2 > (1.5 * max(cs, a_s)) ** 2 for ax, ay, a_s, _ in accepted):
            accepted.append(cand)
    return accepted


def _measure_star(
    data: "np.ndarray", x: float, y: float, sigma0: float,  # type: ignore[name-defined]
) -> dict | None:
    """Measure one star on a local stamp: refined centroid, FWHM and HFD.

    The background is the median of an annulus well outside the star (so it
    follows local sky and neighbouring glow rather than one global value). The
    FWHM comes from windowed second moments, iterated so the weighting window
    converges on the star's own width instead of biasing small. Returns ``None``
    when the source is a single hot pixel, too elongated or has no measurable flux.
    """
    import numpy as np

    half = int(np.ceil(6.0 * sigma0))
    x0, y0 = int(round(x)), int(round(y))
    ylo, yhi = max(0, y0 - half), min(data.shape[0], y0 + half + 1)
    xlo, xhi = max(0, x0 - half), min(data.shape[1], x0 + half + 1)
    stamp = data[ylo:yhi, xlo:xhi]
    yy, xx = np.mgrid[ylo:yhi, xlo:xhi]

    r = np.hypot(xx - x, yy - y)
    ring = (r > 4.0 * sigma0) & (r < 6.0 * sigma0)
    if ring.sum() < 20:
        return None
    flux = stamp - float(np.median(stamp[ring]))

    sigma_w = sigma0
    cx, cy = float(x), float(y)
    for _ in range(4):
        dx, dy = xx - cx, yy - cy
        r2 = dx * dx + dy * dy
        wf = np.exp(-r2 / (2.0 * sigma_w ** 2)) * flux
        total = float(wf.sum())
        if total <= 0:
            return None
        cx += 2.0 * float((wf * dx).sum()) / total
        cy += 2.0 * float((wf * dy).sum()) / total
        m = float((wf * r2).sum()) / (2.0 * total)   # windowed second moment, per axis
        if m <= 0:                                    # noise-dominated: no usable width
            return None
        if m >= 0.98 * sigma_w ** 2:                  # window much narrower than the star
            sigma_f = 1.5 * sigma_w
        else:
            sigma_f = float(np.sqrt(m * sigma_w ** 2 / (sigma_w ** 2 - m)))
        sigma_w = float(np.clip(sigma_f, 0.4, 4.0 * sigma0))

    fwhm = 2.3548 * sigma_w

    dx, dy = xx - cx, yy - cy
    w = np.exp(-(dx * dx + dy * dy) / (2.0 * sigma_w ** 2)) * flux
    wsum = float(w.sum())
    if wsum <= 0:
        return None
    cov = np.array([[(w * dx * dx).sum(), (w * dx * dy).sum()],
                    [(w * dx * dy).sum(), (w * dy * dy).sum()]]) / wsum
    eig = np.linalg.eigvalsh(cov)
    if eig[1] <= 0 or 1.0 - float(np.sqrt(max(eig[0], 0.0) / eig[1])) > _MAX_ELLIPTICITY:
        return None

    # Not a width cut: near perfect focus the moment estimate of a sharp star is biased
    # low by pixel sampling (a pixel-centred star can read well under 1 px), and a width
    # gate then discarded exactly the brightest stars, whose estimate noise doesn't hide
    # that bias. What sets a hot-pixel remnant apart is where its flux sits.
    core = r <= max(3.0, 3.0 * sigma_w)
    core_flux = float(np.maximum(flux[core], 0.0).sum())
    if core_flux <= 0 or float(flux[core].max()) > _MAX_PEAK_FRACTION * core_flux:
        return None

    hfd = _compute_hfd(
        flux, cx - xlo, cy - ylo, max_radius=max(8.0, min(half - 1.0, 4.0 * sigma_w + 2.0)),
    )
    if hfd <= 0:
        return None
    return {"x": cx, "y": cy, "fwhm": fwhm, "hfd": hfd}


def _detect_sync(
    fits_path: str, metric: Metric = "fwhm", reference_stars: list[dict] | None = None,
) -> tuple[float, int, list[dict]]:
    try:
        import numpy as np
        from astropy.io import fits
        from scipy import ndimage  # noqa: F401 — fail early with the install hint
    except ImportError as exc:
        raise RuntimeError(
            f"scipy and astropy are required for star detection. Error: {exc}"
        ) from exc

    with fits.open(fits_path) as hdul:
        data = hdul[0].data  # type: ignore[index]
        if data is None:
            logger.error("autofocus.detecting_stars.no_data", fits_path=fits_path)
            return 0.0, 0, []
        data = data.astype(float)

    # Collapse multi-dimensional data (e.g. [1, H, W]) to 2D
    while data.ndim > 2:
        data = data[0]
    if float(np.ptp(data)) <= 0:
        logger.error("autofocus.detecting_stars.flat_image", fits_path=fits_path)
        return 0.0, 0, []

    data, n_hot = _suppress_hot_pixels(data)
    blobs = _find_blobs(data)

    stars: list[dict] = []
    for bx, by, bsigma, _ in blobs:
        measured = _measure_star(data, bx, by, bsigma)
        if measured is not None:
            stars.append(measured)
            if len(stars) >= _MAX_STARS:
                break
    logger.info(
        "autofocus.detection", hot_pixels=n_hot, blobs=len(blobs), stars=len(stars),
    )
    if not stars:
        return 0.0, 0, []

    if reference_stars:
        matched = _match_reference_stars(stars, reference_stars)
        if not matched:
            logger.warning(
                "autofocus.reference_stars_lost",
                reference=len(reference_stars), detected=len(stars),
            )
            return 0.0, 0, []
        logger.info(
            "autofocus.reference_stars_matched",
            reference=len(reference_stars), matched=len(matched), detected=len(stars),
        )
        stars = matched

    key = "hfd" if metric == "hfd" else "fwhm"
    values = np.array([s[key] for s in stars], dtype=float)
    values = values[_sigma_clip_mask(values)]
    # Report FWHM for every star (the preview annotation uses it whatever the metric).
    return float(np.median(values)), len(stars), [
        {"x": s["x"], "y": s["y"], "fwhm": s["fwhm"]} for s in stars
    ]
