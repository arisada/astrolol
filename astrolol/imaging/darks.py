"""Dark frames for the guide camera: subtraction and hot-pixel detection.

A dark is the median of several frames taken with the scope covered, at the exact settings
(exposure, gain, binning, region) the guider will use. A dark taken over the full frame also
serves any sub-region of it. Hot pixels are the ones that stand out in the dark itself, so
they are known before any star is looked at.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel
from scipy.ndimage import median_filter

from astrolol.devices.base.streaming import Frame

Region = tuple[int, int, int, int]  # x, y, width, height on the binned sensor
Settings = tuple[float, int | None, int]  # exposure, gain, binning


def _robust_sigma(values: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


class DarkInfo(BaseModel):
    exposure: float
    gain: int | None
    binning: int
    region: Region
    frames: int
    hot_pixels: int


@dataclass(frozen=True)
class Dark:
    exposure: float
    gain: int | None
    binning: int
    region: Region
    pixels: np.ndarray  # float32 master
    hot: np.ndarray  # bool, same shape: pixels that stand out from the dark's own level
    frames: int  # how many frames were stacked

    @property
    def settings(self) -> Settings:
        return (self.exposure, self.gain, self.binning)

    def covers(self, frame: Frame) -> bool:
        x, y, w, h = self.region
        fx, fy = frame.origin
        return (
            self.settings == (frame.exposure, frame.gain, frame.binning)
            and x <= fx
            and y <= fy
            and fx + frame.width <= x + w
            and fy + frame.height <= y + h
        )

    def window(self, x0: int, y0: int, x1: int, y1: int) -> tuple[np.ndarray, np.ndarray]:
        """Dark level and hot-pixel mask for [y0:y1, x0:x1] in sensor coordinates."""
        ox, oy, _, _ = self.region
        sl = (slice(y0 - oy, y1 - oy), slice(x0 - ox, x1 - ox))
        return self.pixels[sl], self.hot[sl]


def make_dark(frames: Sequence[Frame], *, hot_sigma: float = 6.0) -> Dark:
    """Stack frames taken with identical settings into a dark."""
    if not frames:
        raise ValueError("need at least one frame")
    first = frames[0]
    if any(f.settings_key != first.settings_key for f in frames):
        raise ValueError("dark frames must share exposure, gain, binning and region")
    stack = np.stack([f.pixels.astype(np.float32) for f in frames])
    master = np.median(stack, axis=0).astype(np.float32)
    # A hot pixel is high relative to the dark's typical level, not relative to a star field.
    level = float(np.median(master))
    sigma = max(_robust_sigma(master), 1e-3)
    hot = master > level + hot_sigma * sigma
    x, y = first.origin
    return Dark(
        exposure=first.exposure,
        gain=first.gain,
        binning=first.binning,
        region=(x, y, first.width, first.height),
        pixels=master,
        hot=hot,
        frames=len(frames),
    )


def heal_hot_pixels(pixels: np.ndarray, hot: np.ndarray) -> np.ndarray:
    """Replace the flagged pixels by the median of their 3x3 neighbourhood (in place)."""
    if hot.any():
        pixels[hot] = median_filter(pixels, size=3)[hot]
    return pixels


class DarkLibrary:
    """Darks by camera settings, optionally persisted as .npz files in *directory*."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory
        self._darks: list[Dark] = []
        if directory is not None and directory.is_dir():
            for path in sorted(directory.glob("dark_*.npz")):
                try:
                    self._darks.append(_load(path))
                except Exception:  # a damaged file must not stop guiding
                    continue

    def __len__(self) -> int:
        return len(self._darks)

    def describe(self) -> list[DarkInfo]:
        return [
            DarkInfo(
                exposure=d.exposure, gain=d.gain, binning=d.binning, region=d.region,
                frames=d.frames, hot_pixels=int(d.hot.sum()),
            )
            for d in self._darks
        ]

    def clear(self) -> None:
        self._darks = []
        if self._directory is not None:
            for path in self._directory.glob("dark_*.npz"):
                path.unlink(missing_ok=True)

    def add(self, dark: Dark) -> None:
        """Store *dark*, replacing one with the same settings and region."""
        self._darks = [
            d for d in self._darks if (d.settings, d.region) != (dark.settings, dark.region)
        ]
        self._darks.append(dark)
        if self._directory is not None:
            self._directory.mkdir(parents=True, exist_ok=True)
            _save(self._directory / _filename(dark), dark)

    def lookup(self, frame: Frame) -> Dark | None:
        """The dark for this frame's settings; the smallest region that covers it wins."""
        covering = [d for d in self._darks if d.covers(frame)]
        return min(covering, key=lambda d: d.region[2] * d.region[3], default=None)

    def prepare(self, frame: Frame) -> np.ndarray:
        """The whole frame, dark-subtracted with hot pixels healed (a float32 copy).

        Without a matching dark the frame is returned as is.
        """
        img = frame.pixels.astype(np.float32)
        dark = self.lookup(frame)
        if dark is None:
            return img
        fx, fy = frame.origin
        level, hot = dark.window(fx, fy, fx + frame.width, fy + frame.height)
        img -= level
        return heal_hot_pixels(img, hot)


def _filename(dark: Dark) -> str:
    key = repr((dark.settings, dark.region)).encode()
    return f"dark_{hashlib.sha1(key).hexdigest()[:12]}.npz"


def _save(path: Path, dark: Dark) -> None:
    np.savez_compressed(
        path,
        pixels=dark.pixels,
        hot=dark.hot,
        meta=np.array(
            [dark.exposure, -1 if dark.gain is None else dark.gain, dark.binning, dark.frames],
            dtype=np.float64,
        ),
        region=np.array(dark.region, dtype=np.int64),
    )


def _load(path: Path) -> Dark:
    with np.load(path) as f:
        exposure, gain, binning, frames = f["meta"].tolist()
        x, y, w, h = (int(v) for v in f["region"])
        return Dark(
            exposure=float(exposure),
            gain=None if gain < 0 else int(gain),
            binning=int(binning),
            region=(x, y, w, h),
            pixels=f["pixels"],
            hot=f["hot"],
            frames=int(frames),
        )
