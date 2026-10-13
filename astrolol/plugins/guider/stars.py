"""Star measurement, detection and guide-star selection.

``measure`` is the single-star primitive: a centre of mass over a small window that is
re-centred a few times. The tracker calls it on small windows every frame; ``detect_stars``
calls it on every peak of a full frame during set-up.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

from astrolol.devices.base.streaming import Frame
from astrolol.plugins.guider.darks import DarkLibrary, heal_hot_pixels


@dataclass(frozen=True)
class Star:
    x: float  # sensor coordinates (binned pixels), pixel centres at integers
    y: float
    peak: float  # above background
    flux: float  # background-subtracted sum in the window
    snr: float  # peak over the window's background noise
    fwhm: float  # pixels; ~0 for a single hot pixel
    saturated: bool = False
    elongation: float = 1.0  # major over minor axis of the light distribution; ~1 for a round star
    hfd: float = 0.0  # half-flux diameter, pixels: twice the flux-weighted mean distance from the centre

    def shifted(self, dx: float, dy: float) -> Star:
        return replace(self, x=self.x + dx, y=self.y + dy)


def _mad_sigma(values: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


FLAT_TOP_PIXELS = 3  # this many pixels sharing the brightest value: the star is clipped


def _saturated(win: np.ndarray, bg: float, noise: float, saturation: float | None, fwhm: float) -> bool:
    """Clipped at the top. Without a known saturation level (the bit depth of a guide camera
    is rarely reported) a star is saturated when it has a plateau: more pixels near its
    brightest value than an unclipped star of its width would have."""
    top = float(win.max())
    if saturation is not None:
        return top >= saturation
    amplitude = top - bg
    if amplitude < 10 * noise:
        return False
    # Clipped pixels differ only by the dark subtracted from them, far less than the photon
    # noise of an unclipped peak.
    tolerance = max(0.5, 0.2 * float(np.sqrt(max(top, 0.0))))
    near_top = int(np.count_nonzero(win >= top - tolerance))
    # A Gaussian star has about 2*pi*sigma^2*f pixels within a fraction f of its peak.
    sigma = max(fwhm, 1.0) / 2.355
    expected = 2 * np.pi * sigma**2 * tolerance / amplitude
    return near_top >= max(FLAT_TOP_PIXELS, 3 * expected + 1)


def measure(
    img: np.ndarray,
    x: float,
    y: float,
    *,
    half: int = 8,
    iterations: int = 3,
    saturation: float | None = None,
) -> Star | None:
    """Measure the star near (x, y) in *img*; None when there is nothing usable there.

    The background and noise come from the border of the window, which is robust as long as
    the window is a few times wider than the star.
    """
    h, w = img.shape
    star: Star | None = None
    for _ in range(iterations):
        x0 = max(int(round(x)) - half, 0)
        y0 = max(int(round(y)) - half, 0)
        x1 = min(int(round(x)) + half + 1, w)
        y1 = min(int(round(y)) + half + 1, h)
        if x1 - x0 < 5 or y1 - y0 < 5:
            return None
        win = img[y0:y1, x0:x1]
        border = np.concatenate((win[0], win[-1], win[1:-1, 0], win[1:-1, -1]))
        bg = float(np.median(border))
        # Never below the rounding of integer pixels: a simulated sky can be perfectly flat.
        noise = max(_mad_sigma(border), 0.3)
        # Pixels within one sigma of the background carry noise, not star: dropping them
        # removes the bias towards the window centre.
        weights = np.clip(win - bg - noise, 0.0, None)
        total = float(weights.sum())
        if total <= 0:
            return None
        ys, xs = np.mgrid[y0:y1, x0:x1]
        x = float((weights * xs).sum() / total)
        y = float((weights * ys).sum() / total)
        peak = float(win.max() - bg)
        # Shape from the pixels above a fifth of the peak (noise stays out of it): a star
        # smeared by motion during the exposure is long along the motion.
        core = np.clip(win - bg - 0.2 * peak, 0.0, None)
        core_total = float(core.sum())
        elongation = 1.0
        if core_total > 0:
            cx = float((core * xs).sum() / core_total)
            cy = float((core * ys).sum() / core_total)
            sxx = float((core * (xs - cx) ** 2).sum() / core_total)
            syy = float((core * (ys - cy) ** 2).sum() / core_total)
            sxy = float((core * (xs - cx) * (ys - cy)).sum() / core_total)
            spread = float(np.sqrt(max((sxx - syy) ** 2 / 4 + sxy**2, 0.0)))
            major, minor = (sxx + syy) / 2 + spread, (sxx + syy) / 2 - spread
            if major > 1.0:  # smaller than about a pixel: a hot pixel, not a shape
                elongation = float(np.sqrt(major / max(minor, 0.05)))
        # FWHM from the area above half maximum: unlike second moments it is not inflated by
        # noise, so a lone hot pixel (area 1 -> 1.13 px) stays narrower than any real star.
        area = int(np.count_nonzero(win - bg > peak / 2))
        fwhm = 2.0 * float(np.sqrt(area / np.pi))
        radius = np.hypot(xs - x, ys - y)
        hfd = 2.0 * float((weights * radius).sum() / total)
        star = Star(
            x=x,
            y=y,
            peak=peak,
            flux=float(np.clip(win - bg, 0.0, None).sum()),
            snr=peak / noise,
            fwhm=fwhm,
            saturated=_saturated(win, bg, noise, saturation, fwhm),
            elongation=elongation,
            hfd=hfd,
        )
    return star


def detect_stars(
    frame: Frame,
    darks: DarkLibrary | None = None,
    *,
    threshold_sigma: float = 6.0,
    half: int = 8,
    edge: int = 12,
    min_fwhm: float = 1.2,
    max_stars: int = 30,
    saturation: float | None = None,
) -> list[Star]:
    """Stars in a full frame, brightest first, in sensor coordinates.

    A frame without a matching dark still works: single-pixel spikes are rejected because
    they are narrower than any star (``min_fwhm``).
    """
    img = darks.prepare(frame) if darks is not None else frame.pixels.astype(np.float32)
    background = float(np.median(img))
    smooth = gaussian_filter(img - background, 1.5)
    noise = max(_mad_sigma(smooth), 1e-3)
    is_peak = (smooth == maximum_filter(smooth, size=2 * 3 + 1)) & (
        smooth > threshold_sigma * noise
    )
    ys, xs = np.nonzero(is_peak)
    order = np.argsort(smooth[ys, xs])[::-1][: max_stars * 4]  # stars fainter than that are noise
    ox, oy = frame.origin
    stars: list[Star] = []
    for i in order:
        px, py = int(xs[i]), int(ys[i])
        if not (edge <= px < frame.width - edge and edge <= py < frame.height - edge):
            continue
        star = measure(img, px, py, half=half, saturation=saturation)
        if star is not None and 1.5 * star.fwhm > half:
            # A broad (defocused, or bloated by seeing) star fills the window, so its wings
            # count as background: measure again in a window sized to it.
            wide = min(int(np.ceil(1.5 * star.fwhm)), 30)
            if edge <= px - wide and px + wide < frame.width and py - wide >= 0 and py + wide < frame.height:
                star = measure(img, px, py, half=wide, saturation=saturation) or star
        if star is None or star.fwhm < min_fwhm:
            continue
        stars.append(star.shifted(ox, oy))
        if len(stars) == max_stars:
            break
    stars.sort(key=lambda s: s.flux, reverse=True)
    return stars


def select_guide_stars(
    stars: list[Star],
    count: int = 3,
    *,
    min_separation: float = 20.0,
    max_fwhm: float = 20.0,
    min_snr: float = 10.0,
    keep: list[Star] | None = None,
    keep_radius: float = 5.0,
    bounds: tuple[float, float, float, float] | None = None,
    margin: float = 0.0,
    prefer: tuple[float, float] | None = None,
) -> list[Star]:
    """The primary guide star followed by companions, best first.

    Stars of *keep* (the previous choice) that are still usable stay, in their order: noise
    would otherwise reshuffle stars of similar brightness from one frame to the next.

    Saturated stars (the centroid flattens), blurred ones and any star with a neighbour
    closer than *min_separation* (the windows would overlap and the pair biases each other)
    are skipped. Brighter is better only up to SNR 100: past that, the centroid is no more
    precise, while a very bright star is nearer to saturating.

    Stars closer than *margin* to the edges of *bounds* (x0, y0, x1, y1, sensor coordinates)
    come last: calibration and dithers move the star, and it must stay in the frame.
    *prefer* (a position the user picked) makes the detected star nearest to it the primary,
    whatever its rank, as long as it is within *keep_radius* × 3.
    """
    def crowded(s: Star) -> bool:
        return any(
            o is not s and np.hypot(o.x - s.x, o.y - s.y) < min_separation for o in stars
        )

    def near_edge(s: Star) -> bool:
        if bounds is None or margin <= 0:
            return False
        x0, y0, x1, y1 = bounds
        return s.x - x0 < margin or x1 - s.x < margin or s.y - y0 < margin or y1 - s.y < margin

    candidates = [s for s in stars if s.snr >= min_snr and s.fwhm <= max_fwhm and not crowded(s)]
    usable = [s for s in candidates if not s.saturated]
    if not usable:
        usable = candidates  # better a clipped star than none (8-bit cameras clip early)
    usable.sort(key=lambda s: (not near_edge(s), min(s.snr, 100.0), s.flux), reverse=True)
    if prefer is not None:
        picked = min(stars, key=lambda s: np.hypot(s.x - prefer[0], s.y - prefer[1]), default=None)
        if picked is not None and np.hypot(picked.x - prefer[0], picked.y - prefer[1]) <= 3 * keep_radius:
            keep = [picked] + [s for s in keep or [] if s is not picked]
            if picked not in usable:  # the user's choice stands, even if we would not have made it
                usable.insert(0, picked)
    kept: list[Star] = []
    for old in keep or []:
        match = min(
            (s for s in usable if s not in kept and np.hypot(s.x - old.x, s.y - old.y) <= keep_radius),
            key=lambda s: np.hypot(s.x - old.x, s.y - old.y),
            default=None,
        )
        if match is not None:
            kept.append(match)
    rest = [s for s in usable if s not in kept]
    return (kept + rest)[:count]
