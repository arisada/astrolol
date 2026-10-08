"""Frame streaming contract: parameters, in-memory frames and latest-wins delivery.

A streaming camera produces ``Frame``s that live in memory only (no FITS file). Consumers
(the guider, a live preview) each hold a ``FrameSubscription`` that keeps just the newest
frame: a slow consumer skips frames instead of falling behind or slowing the camera, because
a guider that processes a stale frame corrects for where the star *was*.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType

import numpy as np
from pydantic import BaseModel, Field


class StreamRoi(BaseModel):
    """Sub-frame in binned sensor pixels. (x, y) is the top-left corner."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class StreamParams(BaseModel):
    exposure: float = Field(gt=0, description="Seconds per frame")
    gain: int | None = Field(default=None, ge=0, description="None = leave driver gain unchanged")
    binning: int = Field(default=1, ge=1, le=4)
    roi: StreamRoi | None = Field(default=None, description="None = full frame")


@dataclass(frozen=True, slots=True)
class Frame:
    """One image in memory. ``pixels`` is 2-D (rows, columns) and must not be modified."""

    pixels: np.ndarray
    seq: int  # per-stream counter, starts at 1
    timestamp: float  # time.monotonic() when the frame was received
    exposure: float
    gain: int | None = None
    binning: int = 1
    # Position of pixels[0, 0] on the binned sensor, so coordinates from a cropped frame
    # map back to the full frame.
    origin: tuple[int, int] = (0, 0)
    meta: dict[str, object] = field(default_factory=dict)

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def settings_key(self) -> tuple[float, int | None, int, tuple[int, int, int, int]]:
        """What a dark frame must match to be applied to this one."""
        return (self.exposure, self.gain, self.binning, (*self.origin, self.width, self.height))


class StreamNotSupported(Exception):
    """The camera has no native streaming mode."""


class StreamClosed(Exception):
    """The stream ended (stopped, or the camera failed: see ``__cause__``)."""


class FrameSubscription:
    """Latest-wins view of a stream. ``async for frame in subscription`` until it ends."""

    def __init__(self, on_close: Callable[[FrameSubscription], None] | None = None) -> None:
        self._on_close = on_close
        self._frame: Frame | None = None
        self._wake = asyncio.Event()
        self._closed = False
        self._error: BaseException | None = None
        self.dropped = 0  # frames replaced before the consumer took them

    def _put(self, frame: Frame) -> None:
        if self._closed:
            return
        if self._frame is not None:
            self.dropped += 1
        self._frame = frame
        self._wake.set()

    def _end(self, error: BaseException | None) -> None:
        if self._closed:
            return
        self._closed = True
        self._error = error
        self._wake.set()

    @property
    def closed(self) -> bool:
        return self._closed

    async def get(self) -> Frame:
        """The next frame newer than the last one returned.

        A frame that arrived before the stream ended is still delivered; after that this
        raises ``StreamClosed`` (chained to the camera error, if any).
        """
        while True:
            if self._frame is not None:
                frame, self._frame = self._frame, None
                return frame
            if self._closed:
                raise StreamClosed("stream ended") from self._error
            self._wake.clear()
            await self._wake.wait()

    def close(self) -> None:
        self._end(None)
        if self._on_close is not None:
            self._on_close(self)

    def __aiter__(self) -> FrameSubscription:
        return self

    async def __anext__(self) -> Frame:
        try:
            return await self.get()
        except StreamClosed as exc:
            if exc.__cause__ is not None:  # the camera failed: don't end quietly
                raise
            raise StopAsyncIteration from None

    async def __aenter__(self) -> FrameSubscription:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class FrameBroadcaster:
    """Fans each published frame out to every subscription."""

    def __init__(self) -> None:
        self._subscriptions: set[FrameSubscription] = set()

    def subscribe(self) -> FrameSubscription:
        sub = FrameSubscription(on_close=self._subscriptions.discard)
        self._subscriptions.add(sub)
        return sub

    def publish(self, frame: Frame) -> None:
        for sub in self._subscriptions:
            sub._put(frame)

    def end(self, error: BaseException | None = None) -> None:
        """End every subscription (consumers see the error, if given, as StreamClosed's cause)."""
        for sub in list(self._subscriptions):
            sub._end(error)
        self._subscriptions.clear()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)
