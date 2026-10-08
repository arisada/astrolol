"""What the guide camera sees right now: the latest frame, and the stars drawn over it."""

from __future__ import annotations

import io
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel

from astrolol.devices.base.streaming import Frame

StarKind = Literal["primary", "companion", "candidate", "lost"]
ViewMode = Literal["idle", "preview", "guiding"]


class OverlayStar(BaseModel):
    x: float  # sensor coordinates (binned pixels)
    y: float
    kind: StarKind
    snr: float | None = None
    fwhm: float | None = None
    half: int = 8  # half-size of the window the tracker measures


class ViewInfo(BaseModel):
    mode: ViewMode
    version: int  # changes with every new frame: fetch the image again when it does
    width: int
    height: int
    origin: tuple[int, int]  # sensor position of the image's top-left pixel
    stars: list[OverlayStar]
    locks: list[tuple[float, float]] = []  # where the guided stars should be


def render_jpeg(pixels: np.ndarray, max_width: int = 960, quality: int = 80) -> bytes:
    """A stretched 8-bit JPEG: star fields are mostly dark, so the range is cut at the
    background and a bright percentile, and compressed with a square root."""
    img = pixels.astype(np.float32)
    lo, hi = np.percentile(img[:: max(1, img.shape[0] // 256), :: max(1, img.shape[1] // 256)], (5, 99.8))
    if hi <= lo:
        hi = lo + 1.0
    scaled = np.sqrt(np.clip((img - lo) / (hi - lo), 0.0, 1.0))
    image = Image.fromarray((scaled * 255).astype(np.uint8), mode="L")
    if image.width > max_width:
        image = image.reduce(-(-image.width // max_width))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


class GuideView:
    def __init__(self) -> None:
        self._frame: Frame | None = None
        self._stars: list[OverlayStar] = []
        self._locks: list[tuple[float, float]] = []
        self._mode: ViewMode = "idle"
        self._version = 0
        self._jpeg: tuple[int, bytes] | None = None

    def update(
        self,
        frame: Frame,
        stars: list[OverlayStar],
        mode: ViewMode,
        locks: list[tuple[float, float]] | None = None,
    ) -> None:
        self._frame, self._stars, self._mode = frame, stars, mode
        self._locks = locks or []
        self._version += 1

    def go_idle(self) -> None:
        """Keep the last image but drop the overlay: its stars no longer mean anything."""
        self._stars, self._locks, self._mode = [], [], "idle"
        self._version += 1

    def info(self) -> ViewInfo:
        f = self._frame
        return ViewInfo(
            mode=self._mode,
            version=self._version,
            width=f.width if f else 0,
            height=f.height if f else 0,
            origin=f.origin if f else (0, 0),
            stars=self._stars,
            locks=self._locks,
        )

    def jpeg(self) -> bytes | None:
        if self._frame is None:
            return None
        if self._jpeg is None or self._jpeg[0] != self._version:
            self._jpeg = (self._version, render_jpeg(self._frame.pixels))
        return self._jpeg[1]
