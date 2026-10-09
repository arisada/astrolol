"""Follows the chosen guide stars from frame to frame, measuring only a small window of each.

A full-frame pass costs milliseconds on a Raspberry Pi but a window costs microseconds, and
the window is where the dark frame matters: only the pixels around each star are
dark-subtracted and healed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.ndimage import gaussian_filter

from astrolol.devices.base.streaming import Frame
from plugins.guider.darks import DarkLibrary, heal_hot_pixels
from plugins.guider.stars import Star, measure


ReadingState = Literal["ok", "blurred", "lost"]


@dataclass(frozen=True)
class StarReading:
    """One star in one frame.

    "blurred": the star is there but smeared (it moved during the exposure), so its position
    is not trustworthy: wait for the next frame instead of acting on it. "lost": it is not
    there at all (cloud, left the window).
    """

    star: Star | None  # None only when lost
    dx: float | None  # displacement from the lock position, pixels; only when ok
    dy: float | None
    state: ReadingState = "ok"


@dataclass(frozen=True)
class TrackerResult:
    readings: list[StarReading]
    dx: float | None  # median displacement of the stars found; None when none were found
    dy: float | None

    @property
    def found(self) -> int:
        return sum(1 for r in self.readings if r.state == "ok")

    @property
    def blurred(self) -> int:
        return sum(1 for r in self.readings if r.state == "blurred")


class StarTracker:
    """Tracks stars locked at the positions given (sensor coordinates).

    The reported offset is the median over the stars still found, so one star lost to a
    cloud edge, a satellite or a hot pixel does not shift the correction. Stars whose flux
    falls below *min_flux_ratio* of their locked flux count as lost.
    """

    def __init__(
        self,
        stars: list[Star],
        darks: DarkLibrary | None = None,
        *,
        half: int = 8,
        margin: int = 6,
        min_snr: float = 4.0,
        min_flux_ratio: float = 0.4,
        saturation: float | None = None,
        max_elongation: float = 1.8,
        max_fwhm_ratio: float = 1.7,
    ) -> None:
        if not stars:
            raise ValueError("need at least one star to track")
        self._locks = [(s.x, s.y) for s in stars]
        self._ref_flux = [s.flux for s in stars]
        self._ref_fwhm = [s.fwhm for s in stars]
        self._max_elongation = max_elongation
        self._max_fwhm_ratio = max_fwhm_ratio
        self._last = [(s.x, s.y) for s in stars]
        self._darks = darks
        self._half = half
        self._margin = margin
        self._min_snr = min_snr
        self._min_flux_ratio = min_flux_ratio
        self._saturation = saturation

    @property
    def half(self) -> int:
        return self._half

    @property
    def last_positions(self) -> list[tuple[float, float]]:
        """Where each star was last seen (sensor coordinates)."""
        return list(self._last)

    @property
    def lock_positions(self) -> list[tuple[float, float]]:
        return list(self._locks)

    def reset_lock(self, offset: tuple[float, float] = (0.0, 0.0)) -> None:
        """Make the stars' last positions (plus *offset*) the new lock positions."""
        self._locks = [(x + offset[0], y + offset[1]) for x, y in self._last]

    def refresh(self, frame: Frame, *, relock: bool = True) -> int:
        """Re-measure every star in *frame* with this tracker's window and lock on the result.

        With ``relock=False`` only the reference brightness and shape are renewed (the stream
        changed exposure): the lock positions stay where the guider wants the stars.

        Detection may have used a different window than tracking will; this makes the
        reference flux and lock positions consistent with what ``update`` measures.
        Returns how many stars were found.
        """
        dark = self._darks.lookup(frame) if self._darks is not None else None
        found = 0
        for i, (x, y) in enumerate(self._last):
            star = self._measure(frame, dark, x, y, i, check_flux=False)
            if star is not None:
                self._last[i] = (star.x, star.y)
                if relock:
                    self._locks[i] = self._last[i]
                self._ref_flux[i] = star.flux
                self._ref_fwhm[i] = star.fwhm
                found += 1
        return found

    def shift_lock(self, dx: float, dy: float) -> None:
        """Move where the stars should be (a dither): the controller then walks them there."""
        self._locks = [(x + dx, y + dy) for x, y in self._locks]

    def update(self, frame: Frame) -> TrackerResult:
        dark = self._darks.lookup(frame) if self._darks is not None else None
        readings: list[StarReading] = []
        for i, (lx, ly) in enumerate(self._locks):
            star = self._measure(frame, dark, *self._last[i], i)
            if star is None:
                readings.append(StarReading(None, None, None, "lost"))
                continue
            self._last[i] = (star.x, star.y)
            if self._smeared(star, i):
                readings.append(StarReading(star, None, None, "blurred"))
                continue
            readings.append(StarReading(star, star.x - lx, star.y - ly))
        good = [r for r in readings if r.state == "ok"]
        if not good:
            return TrackerResult(readings, None, None)
        return TrackerResult(
            readings,
            float(np.median([r.dx for r in good])),
            float(np.median([r.dy for r in good])),
        )

    def _smeared(self, star: Star, i: int) -> bool:
        return star.elongation > self._max_elongation or star.fwhm > self._max_fwhm_ratio * self._ref_fwhm[i]

    def reacquire(self, frame: Frame, radius: int = 60, indices: list[int] | None = None) -> int:
        """Look for stars that have moved out of their window, within *radius* pixels.

        Picks the brightest peak there that looks like the star (flux and SNR as in
        ``update``) and resumes tracking from it. Returns how many were found again.
        """
        dark = self._darks.lookup(frame) if self._darks is not None else None
        ox, oy = frame.origin
        found = 0
        for i in indices if indices is not None else range(len(self._last)):
            ex, ey = self._last[i]
            x0, y0 = max(int(ex - ox) - radius, 0), max(int(ey - oy) - radius, 0)
            x1, y1 = min(int(ex - ox) + radius + 1, frame.width), min(int(ey - oy) + radius + 1, frame.height)
            if x1 - x0 < 2 * self._half or y1 - y0 < 2 * self._half:
                continue
            crop = self._crop(frame, dark, x0, y0, x1, y1)
            smooth = gaussian_filter(crop - float(np.median(crop)), 1.5)
            peaks = np.argsort(smooth, axis=None)[::-1][:1]  # the brightest spot; others rarely are the star
            for flat in peaks:
                py, px = divmod(int(flat), smooth.shape[1])
                star = self._measure(frame, dark, px + x0 + ox, py + y0 + oy, i)
                if star is not None:
                    self._last[i] = (star.x, star.y)
                    found += 1
        return found

    def _crop(self, frame: Frame, dark, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:  # noqa: ANN001
        ox, oy = frame.origin
        crop = frame.pixels[y0:y1, x0:x1].astype(np.float32)
        if dark is not None:
            level, hot = dark.window(x0 + ox, y0 + oy, x1 + ox, y1 + oy)
            crop -= level
            heal_hot_pixels(crop, hot)
        return crop

    def _measure(self, frame: Frame, dark, x: float, y: float, i: int, check_flux: bool = True) -> Star | None:  # noqa: ANN001
        ox, oy = frame.origin
        reach = self._half + self._margin
        cx, cy = int(round(x - ox)), int(round(y - oy))
        x0, y0 = max(cx - reach, 0), max(cy - reach, 0)
        x1, y1 = min(cx + reach + 1, frame.width), min(cy + reach + 1, frame.height)
        if x1 - x0 < 2 * self._half or y1 - y0 < 2 * self._half:
            return None
        crop = self._crop(frame, dark, x0, y0, x1, y1)
        saturation = self._saturation
        star = measure(crop, x - ox - x0, y - oy - y0, half=self._half, saturation=saturation)
        if star is None or star.snr < self._min_snr:
            return None
        if check_flux and star.flux < self._min_flux_ratio * self._ref_flux[i]:
            return None
        return star.shifted(ox + x0, oy + y0)
