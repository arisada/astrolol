"""What the guide camera sees right now: the latest frame, and the stars drawn over it."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel

from astrolol.devices.base.streaming import Frame
from astrolol.imaging.darks import DarkLibrary
from astrolol.imaging.frameview import FrameStats, OverlayStar, StarKind, frame_stats, render_jpeg

__all__ = ["FrameStats", "GuideView", "OverlayStar", "StarKind", "ViewInfo", "render_jpeg"]

ViewMode = Literal["idle", "preview", "calibrating", "guiding"]


class ViewInfo(BaseModel):
    mode: ViewMode
    version: int  # changes with every new frame: fetch the image again when it does
    width: int
    height: int
    origin: tuple[int, int]  # sensor position of the image's top-left pixel
    stars: list[OverlayStar]
    locks: list[tuple[float, float]] = []  # where the guided stars should be
    pixel_scale: float | None = None  # arcsec per pixel, when known
    stats: FrameStats | None = None
    dark_applied: bool = False  # the image is shown after its dark: hot pixels removed


class GuideView:
    def __init__(self, darks: DarkLibrary | None = None) -> None:
        self._darks = darks
        self._frame: Frame | None = None
        self._stars: list[OverlayStar] = []
        self._locks: list[tuple[float, float]] = []
        self._mode: ViewMode = "idle"
        self._version = 0
        self._jpeg: tuple[int, bytes] | None = None
        self._period = 0.0
        self._stats: tuple[int, FrameStats] | None = None
        self._prepared: tuple[int, np.ndarray] | None = None
        self.pixel_scale: float | None = None

    def update(
        self,
        frame: Frame,
        stars: list[OverlayStar],
        mode: ViewMode,
        locks: list[tuple[float, float]] | None = None,
        period: float = 0.0,
    ) -> None:
        self._frame, self._stars, self._mode = frame, stars, mode
        self._period = period
        self._locks = locks or []
        self._version += 1

    @property
    def stars(self) -> list[OverlayStar]:
        return self._stars

    @property
    def frame(self) -> Frame | None:
        return self._frame

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
            pixel_scale=self.pixel_scale,
            stats=self._frame_stats(),
            dark_applied=f is not None and self._shown()[1],
        )

    def _shown(self) -> tuple[np.ndarray, bool]:
        """What the image shows: the frame after its dark when there is one, else as it came."""
        f = self._frame
        assert f is not None
        if self._darks is not None and self._darks.lookup(f) is not None:
            if self._prepared is None or self._prepared[0] != self._version:
                self._prepared = (self._version, self._darks.prepare(f))
            return self._prepared[1], True
        return f.pixels, False

    def _frame_stats(self) -> FrameStats | None:
        f = self._frame
        if f is None:
            return None
        if self._stats is None or self._stats[0] != self._version:
            self._stats = (self._version, frame_stats(f, self._period, self._shown()[0]))
        return self._stats[1]

    def jpeg(self) -> bytes | None:
        if self._frame is None:
            return None
        if self._jpeg is None or self._jpeg[0] != self._version:
            self._jpeg = (self._version, render_jpeg(self._shown()[0]))
        return self._jpeg[1]
