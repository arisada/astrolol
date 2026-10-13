"""Follows the chosen guide stars from frame to frame, measuring only a small window of each.

A full-frame pass costs milliseconds on a Raspberry Pi but a window costs microseconds, and
the window is where the dark frame matters: only the pixels around each star are
dark-subtracted and healed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

from astrolol.devices.base.streaming import Frame
from astrolol.plugins.guider.darks import DarkLibrary, heal_hot_pixels
from astrolol.plugins.guider.stars import Star, measure


ReadingState = Literal["ok", "blurred", "lost", "outlier"]

REF_ADAPT = 0.05  # weight of each good frame in the reference brightness and shape
MATCH_PX = 3.0  # two stars further apart than this after a shift are not the same star


@dataclass(frozen=True)
class StarReading:
    """One star in one frame.

    "blurred": the star is there but smeared (it moved during the exposure), so its position
    is not trustworthy: wait for the next frame instead of acting on it. "lost": it is not
    there at all (cloud, left the window), or something else is (brightness far off).
    "outlier": measured, but it disagrees with the other guide stars, so it is left out.
    """

    star: Star | None  # None only when lost
    dx: float | None  # displacement from the lock position, pixels; ok and outlier only
    dy: float | None
    state: ReadingState = "ok"


@dataclass(frozen=True)
class TrackerResult:
    readings: list[StarReading]
    dx: float | None  # mean displacement of the agreeing stars; None when none were found
    dy: float | None

    @property
    def found(self) -> int:
        return sum(1 for r in self.readings if r.state == "ok")

    @property
    def blurred(self) -> int:
        return sum(1 for r in self.readings if r.state == "blurred")


class StarTracker:
    """Tracks stars locked at the positions given (sensor coordinates).

    The reported offset is the mean over the stars that agree with each other (the median
    picks them), so one star lost to a cloud edge, a satellite or a hot pixel does not shift
    the correction while several good stars average their seeing out. A star whose flux
    leaves [*min_flux_ratio*, *max_flux_ratio*] of its reference counts as lost: it faded,
    or the window now holds something else. The references follow slow changes (the target
    sinking into haze, the seeing worsening) so that those do not end guiding.
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
        max_flux_ratio: float = 2.5,
        saturation: float | None = None,
        max_elongation: float = 1.8,
        max_fwhm_ratio: float = 1.7,
    ) -> None:
        if not stars:
            raise ValueError("need at least one star to track")
        self._locks = [(s.x, s.y) for s in stars]
        self._ref_flux = [s.flux for s in stars]
        self._ref_fwhm = [s.fwhm for s in stars]
        self._ref_elong = [s.elongation for s in stars]
        self._max_elongation = max_elongation
        self._max_fwhm_ratio = max_fwhm_ratio
        self._last = [(s.x, s.y) for s in stars]
        self._darks = darks
        self._half = half
        self._margin = margin
        self._min_snr = min_snr
        self._min_flux_ratio = min_flux_ratio
        self._max_flux_ratio = max_flux_ratio
        self._saturation = saturation

    @property
    def half(self) -> int:
        return self._half

    @property
    def count(self) -> int:
        return len(self._locks)

    @property
    def last_positions(self) -> list[tuple[float, float]]:
        """Where each star was last seen (sensor coordinates)."""
        return list(self._last)

    @property
    def lock_positions(self) -> list[tuple[float, float]]:
        return list(self._locks)

    @property
    def reference_flux(self) -> list[float]:
        return list(self._ref_flux)

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
                self._ref_elong[i] = star.elongation
                found += 1
        return found

    def shift_lock(self, dx: float, dy: float) -> None:
        """Move where the stars should be (a dither): the controller then walks them there."""
        self._locks = [(x + dx, y + dy) for x, y in self._locks]

    def shift_last(self, dx: float, dy: float) -> None:
        """Expect the stars *dx*, *dy* away from where they were last seen (a known move)."""
        self._last = [(x + dx, y + dy) for x, y in self._last]

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
        readings = self._reject_outliers(readings)
        good = [(i, r) for i, r in enumerate(readings) if r.state == "ok"]
        for i, r in good:
            self._adapt(i, r.star)  # type: ignore[arg-type]
        if not good:
            return TrackerResult(readings, None, None)
        return TrackerResult(
            readings,
            float(np.mean([r.dx for _, r in good])),
            float(np.mean([r.dy for _, r in good])),
        )

    @staticmethod
    def _reject_outliers(readings: list[StarReading]) -> list[StarReading]:
        """Leave out stars whose displacement disagrees with the others' (needs three)."""
        good = [r for r in readings if r.state == "ok"]
        if len(good) < 3:
            return readings
        mx = float(np.median([r.dx for r in good]))
        my = float(np.median([r.dy for r in good]))
        dist = np.array([np.hypot(r.dx - mx, r.dy - my) for r in good])  # type: ignore[operator]
        limit = max(1.0, 4.0 * 1.4826 * float(np.median(dist)))
        return [
            StarReading(r.star, r.dx, r.dy, "outlier")
            if r.state == "ok" and np.hypot(r.dx - mx, r.dy - my) > limit  # type: ignore[operator]
            else r
            for r in readings
        ]

    def _adapt(self, i: int, star: Star) -> None:
        self._ref_flux[i] += REF_ADAPT * (star.flux - self._ref_flux[i])
        self._ref_fwhm[i] += REF_ADAPT * (star.fwhm - self._ref_fwhm[i])
        self._ref_elong[i] += REF_ADAPT * (star.elongation - self._ref_elong[i])

    def _smeared(self, star: Star, i: int) -> bool:
        # Relative to the star as it was locked: off-axis and guide-scope stars are often
        # never round, and they must still be guided on.
        max_elong = max(self._max_elongation, 1.4 * self._ref_elong[i])
        return star.elongation > max_elong or star.fwhm > self._max_fwhm_ratio * self._ref_fwhm[i]

    def _looks_like(self, star: Star, i: int) -> bool:
        ratio = star.flux / max(self._ref_flux[i], 1e-6)
        return (
            self._min_flux_ratio <= ratio <= self._max_flux_ratio
            and star.fwhm <= self._max_fwhm_ratio * max(self._ref_fwhm[i], 1.0)
        )

    def reacquire(self, frame: Frame, radius: int = 60, indices: list[int] | None = None) -> int:
        """Look for stars that have moved out of their window, within *radius* pixels.

        Of the peaks there that look like the star (brightness and size near its reference),
        takes the one nearest to where it was last seen, and resumes tracking from it.
        Returns how many were found again.
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
            noise = max(float(1.4826 * np.median(np.abs(smooth - np.median(smooth)))), 1e-3)
            peaks = (smooth == maximum_filter(smooth, size=7)) & (smooth > 5 * noise)
            ys, xs = np.nonzero(peaks)
            order = np.argsort(smooth[ys, xs])[::-1][:12]
            best: Star | None = None
            for k in order:
                star = self._measure(frame, dark, float(xs[k] + x0 + ox), float(ys[k] + y0 + oy), i, check_flux=False)
                if star is None or not self._looks_like(star, i):
                    continue
                if best is None or np.hypot(star.x - ex, star.y - ey) < np.hypot(best.x - ex, best.y - ey):
                    best = star
            if best is not None:
                self._last[i] = (best.x, best.y)
                found += 1
        return found

    def relocate(self, detected: list[Star]) -> tuple[float, float] | None:
        """Find the guide stars anywhere among *detected* (a full frame) after a big move.

        Each detected star that looks like the primary proposes a shift; the shift under which
        the most guide stars land on a detected star wins (one star alone must also match in
        brightness). On success every star's expected position moves by it.
        """
        if not detected:
            return None
        n = len(self._last)
        best: tuple[int, float, tuple[float, float]] | None = None
        for d in detected:
            ratio = d.flux / max(self._ref_flux[0], 1e-6)
            if not self._min_flux_ratio <= ratio <= self._max_flux_ratio:
                continue
            shift = (d.x - self._last[0][0], d.y - self._last[0][1])
            score = 1
            for j in range(1, n):
                ex, ey = self._last[j][0] + shift[0], self._last[j][1] + shift[1]
                if any(np.hypot(o.x - ex, o.y - ey) < MATCH_PX for o in detected):
                    score += 1
            size = float(np.hypot(*shift))
            if best is None or (score, -size) > (best[0], -best[1]):
                best = (score, size, shift)
        if best is None or best[0] < min(n, 2):
            return None
        self.shift_last(*best[2])
        return best[2]

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
        star = measure(crop, x - ox - x0, y - oy - y0, half=self._half, saturation=self._saturation)
        if star is None or star.snr < self._min_snr:
            return None
        if check_flux:
            ratio = star.flux / max(self._ref_flux[i], 1e-6)
            if not self._min_flux_ratio <= ratio <= self._max_flux_ratio:
                return None
        return star.shifted(ox + x0, oy + y0)
