"""A synthetic guide camera + mount with known behaviour, for closed-loop tests."""
from __future__ import annotations

import asyncio
import contextlib
import math
import time

import numpy as np

from astrolol.core.guiding.errors import GuiderNotConnected
from astrolol.devices.base.streaming import Frame, FrameBroadcaster, FrameSubscription, StreamParams


class Rig:
    """Stars move with pulses through *matrix* (pixels per ms; columns West, North), drift
    steadily, and Dec reversals lose *dec_backlash_ms* of pulse."""

    def __init__(
        self,
        matrix: np.ndarray = ((0.030, 0.0), (0.0, 0.030)),
        stars: tuple[tuple[float, float, float], ...] = ((100.0, 80.0, 700.0), (60.0, 50.0, 500.0), (150.0, 110.0, 450.0)),
        drift: tuple[float, float] = (4.0, 0.0),  # pixels per second
        dec_backlash_ms: float = 0.0,
        shape: tuple[int, int] = (160, 200),
        seed: int = 0,
        time_scale: float = 0.05,
        smear_frames_after_pulse: int = 0,
        lose_frames_after_pulse: int = 0,
        dec_wobble: tuple[float, float] = (0.0, 1.0),
    ) -> None:
        self.time_scale = time_scale
        self.smear_frames = smear_frames_after_pulse  # stars smeared along x for this many frames
        self.lose_frames = lose_frames_after_pulse  # stars invisible for this many frames
        self.dec_wobble = dec_wobble  # (amplitude px, period s): a Dec swing that forces reversals
        self._glitch = 0
        self.matrix = np.array(matrix, dtype=float)
        self.stars = stars
        self.drift = np.array(drift)
        self.dec_backlash_ms = dec_backlash_ms
        self.shape = shape
        self.rng = np.random.default_rng(seed)
        self.offset = np.zeros(2)
        self._t0 = time.monotonic()
        self._broadcaster = FrameBroadcaster()
        self._task: asyncio.Task[None] | None = None
        self._dec_dir = 0
        self._dec_slack = 0.0
        self.pulses: list[tuple[str, int]] = []
        self.hidden = False  # stars invisible (clouds)
        self.drift_enabled = True

    # -- IStreamingCamera
    def subscribe_frames(self) -> FrameSubscription:
        return self._broadcaster.subscribe()

    async def start_stream(self, params: StreamParams) -> None:
        self._task = asyncio.create_task(self._produce(params))

    async def stop_stream(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._broadcaster.end()

    # -- IPulseGuider
    async def pulse_guide(self, direction: str, duration_ms: int) -> None:
        self.pulses.append((direction, duration_ms))
        await asyncio.sleep(duration_ms / 1000 * self.time_scale)  # a pulse takes (scaled) time
        ra = {"W": 1, "E": -1}.get(direction, 0) * duration_ms
        dec = {"N": 1, "S": -1}.get(direction, 0) * duration_ms
        if dec:
            sign = 1 if dec > 0 else -1
            if sign != self._dec_dir:
                self._dec_dir, self._dec_slack = sign, self.dec_backlash_ms
            take = min(self._dec_slack, abs(dec))
            self._dec_slack -= take
            dec = sign * (abs(dec) - take)
        self.offset += self.matrix @ np.array([ra, dec], dtype=float)
        self._glitch = max(self.smear_frames, self.lose_frames)

    # -- internals
    def star_positions(self) -> list[tuple[float, float]]:
        t = time.monotonic() - self._t0
        shift = self.offset + (self.drift * t if self.drift_enabled else 0)
        amp, period = self.dec_wobble
        if amp:
            shift = shift + np.array([0.0, amp * math.sin(2 * math.pi * t / period)])
        return [(x + shift[0], y + shift[1]) for x, y, _ in self.stars]

    async def _produce(self, params: StreamParams) -> None:
        seq = 0
        roi = params.roi
        ox, oy = (roi.x, roi.y) if roi else (0, 0)
        h, w = (roi.height, roi.width) if roi else self.shape
        ys, xs = np.mgrid[0:h, 0:w]
        while True:
            await asyncio.sleep(params.exposure)
            img = 100 + self.rng.normal(0, 3, (h, w))
            glitched, self._glitch = self._glitch > 0, max(self._glitch - 1, 0)
            smear = glitched and self.smear_frames > 0
            hidden = self.hidden or (glitched and self.lose_frames > 0)
            if not hidden:
                sx = 8.0 if smear else 1.8  # motion during the exposure: long along x, and dimmer
                for (x, y), (_, _, amp) in zip(self.star_positions(), self.stars):
                    img += amp * (0.4 if smear else 1.0) * np.exp(-((xs - (x - ox)) ** 2 / (2 * sx**2) + (ys - (y - oy)) ** 2 / (2 * 1.8**2)))
            seq += 1
            self._broadcaster.publish(
                Frame(
                    pixels=np.clip(img, 0, 65535).astype(np.uint16), seq=seq, timestamp=time.monotonic(),
                    exposure=params.exposure, gain=params.gain, binning=params.binning, origin=(ox, oy),
                )
            )


class RigDevices:
    def __init__(self, rig: Rig | None) -> None:
        self.rig = rig

    def camera(self):  # noqa: ANN201
        if self.rig is None:
            raise GuiderNotConnected("no guide camera")
        return self.rig

    def pulse_guider(self):  # noqa: ANN201
        return self.camera()
