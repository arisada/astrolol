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
from plugins.guider.darks import DarkLibrary, heal_hot_pixels


@dataclass(frozen=True)
class Star:
    x: float  # sensor coordinates (binned pixels), pixel centres at integers
    y: float
    peak: float  # above background
    flux: float  # background-subtracted sum in the window
    snr: float  # peak over the window's background noise
    fwhm: float  # pixels; ~0 for a single hot pixel
    saturated: bool = False

    def shifted(self, dx: float, dy: float) -> Star:
        return replace(self, x=self.x + dx, y=self.y + dy)


def _mad_sigma(values: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


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
        noise = max(_mad_sigma(border), 1e-3)
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
        # FWHM from the area above half maximum: unlike second moments it is not inflated by
        # noise, so a lone hot pixel (area 1 -> 1.13 px) stays narrower than any real star.
        area = int(np.count_nonzero(win - bg > peak / 2))
        fwhm = 2.0 * float(np.sqrt(area / np.pi))
        star = Star(
            x=x,
            y=y,
            peak=peak,
            flux=float(np.clip(win - bg, 0.0, None).sum()),
            snr=peak / noise,
            fwhm=fwhm,
            saturated=saturation is not None and float(win.max()) >= saturation,
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
    max_fwhm: float = 12.0,
    min_snr: float = 10.0,
) -> list[Star]:
    """The primary guide star followed by companions, best first.

    Saturated stars (the centroid flattens), blurred ones and any star with a neighbour
    closer than *min_separation* (the windows would overlap and the pair biases each other)
    are skipped. Brighter is better only up to SNR 100: past that, the centroid is no more
    precise, while a very bright star is nearer to saturating.
    """
    def crowded(s: Star) -> bool:
        return any(
            o is not s and np.hypot(o.x - s.x, o.y - s.y) < min_separation for o in stars
        )

    usable = [
        s
        for s in stars
        if not s.saturated and s.snr >= min_snr and s.fwhm <= max_fwhm and not crowded(s)
    ]
    usable.sort(key=lambda s: min(s.snr, 100.0), reverse=True)
    return usable[:count]
