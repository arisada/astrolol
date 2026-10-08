"""Follows the chosen guide stars from frame to frame, measuring only a small window of each.

A full-frame pass costs milliseconds on a Raspberry Pi but a window costs microseconds, and
the window is where the dark frame matters: only the pixels around each star are
dark-subtracted and healed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrolol.devices.base.streaming import Frame
from plugins.guider.darks import DarkLibrary, heal_hot_pixels
from plugins.guider.stars import Star, measure


@dataclass(frozen=True)
class StarReading:
    star: Star | None  # None: the star is not there (lost, or the window left the frame)
    dx: float | None  # displacement from the lock position, pixels
    dy: float | None


@dataclass(frozen=True)
class TrackerResult:
    readings: list[StarReading]
    dx: float | None  # median displacement of the stars found; None when none were found
    dy: float | None

    @property
    def found(self) -> int:
        return sum(1 for r in self.readings if r.star is not None)


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
    ) -> None:
        if not stars:
            raise ValueError("need at least one star to track")
        self._locks = [(s.x, s.y) for s in stars]
        self._ref_flux = [s.flux for s in stars]
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

    def refresh(self, frame: Frame) -> int:
        """Re-measure every star in *frame* with this tracker's window and lock on the result.

        Detection may have used a different window than tracking will; this makes the
        reference flux and lock positions consistent with what ``update`` measures.
        Returns how many stars were found.
        """
        dark = self._darks.lookup(frame) if self._darks is not None else None
        found = 0
        for i, (x, y) in enumerate(self._last):
            star = self._measure(frame, dark, x, y, i, check_flux=False)
            if star is not None:
                self._locks[i] = self._last[i] = (star.x, star.y)
                self._ref_flux[i] = star.flux
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
                readings.append(StarReading(None, None, None))
                continue
            self._last[i] = (star.x, star.y)
            readings.append(StarReading(star, star.x - lx, star.y - ly))
        found = [r for r in readings if r.star is not None]
        if not found:
            return TrackerResult(readings, None, None)
        return TrackerResult(
            readings,
            float(np.median([r.dx for r in found])),
            float(np.median([r.dy for r in found])),
        )

    def _measure(self, frame: Frame, dark, x: float, y: float, i: int, check_flux: bool = True) -> Star | None:  # noqa: ANN001
        ox, oy = frame.origin
        reach = self._half + self._margin
        cx, cy = int(round(x - ox)), int(round(y - oy))
        x0, y0 = max(cx - reach, 0), max(cy - reach, 0)
        x1, y1 = min(cx + reach + 1, frame.width), min(cy + reach + 1, frame.height)
        if x1 - x0 < 2 * self._half or y1 - y0 < 2 * self._half:
            return None
        crop = frame.pixels[y0:y1, x0:x1].astype(np.float32)
        if dark is not None:
            level, hot = dark.window(x0 + ox, y0 + oy, x1 + ox, y1 + oy)
            crop -= level
            heal_hot_pixels(crop, hot)
        saturation = self._saturation
        star = measure(crop, x - ox - x0, y - oy - y0, half=self._half, saturation=saturation)
        if star is None or star.snr < self._min_snr:
            return None
        if check_flux and star.flux < self._min_flux_ratio * self._ref_flux[i]:
            return None
        return star.shifted(ox + x0, oy + y0)
