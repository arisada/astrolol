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
        seeing_px: float = 0.0,
        pe: tuple[float, float] = (0.0, 1.0),
        star_sigma: tuple[float, float] = (1.8, 1.8),
        max_adu: int = 65535,
        dec: float | None = None,
        pier_side: str | None = None,
        sky_dec_pulses: bool = False,
        pulse_latency: float = 0.0,
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
        self.exposures: list[float] = []  # the exposure of each stream started
        self.hidden = False  # stars invisible (clouds)
        self.drift_enabled = True
        self.seeing_px = seeing_px  # random jitter of each frame's star positions
        self.pe = pe  # (amplitude px, period s): periodic error along the RA axis
        self.star_sigma = star_sigma  # (x, y) Gaussian sigma: unequal for elongated stars
        self.max_adu = max_adu  # where the camera clips
        # Pointing, for guiders that ask the mount. Dec in degrees, pier side "East"/"West".
        self.dec, self.pier_side = dec, pier_side
        # True: North means the sky's north on either side of the pier (the mount's driver
        # handles it); False: North drives the Dec motor one fixed way (an ST4 cable).
        self.sky_dec_pulses = sky_dec_pulses
        self.pulse_latency = pulse_latency  # seconds before a pulse starts moving the mount
        self.slewing = False
        self.tracking = True
        self.fail_pulses = 0  # the next this many pulses raise
        self.stalled = False  # no frames while set (a stuck camera)

    # -- IStreamingCamera
    def subscribe_frames(self) -> FrameSubscription:
        return self._broadcaster.subscribe()

    async def start_stream(self, params: StreamParams) -> None:
        self.exposures.append(params.exposure)
        self._task = asyncio.create_task(self._produce(params))

    async def stop_stream(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._broadcaster.end()

    # -- IPulseGuider
    def end_stream(self, error: BaseException) -> None:
        """The camera fails: the stream ends with *error*."""
        task, self._task = self._task, None
        if task:
            task.cancel()
        self._broadcaster.end(error)

    def flip(self) -> None:
        """A meridian flip: the camera turns half a turn around the sky with the tube, so a
        West pulse moves the star the other way on the sensor; North does too when it follows
        the sky, and stays put when it drives the motor a fixed way."""
        self.pier_side = {"East": "West", "West": "East"}.get(self.pier_side or "", "West")
        self.matrix[:, 0] *= -1
        if not self.sky_dec_pulses:
            return
        self.matrix[:, 1] *= -1
        self._dec_dir = -self._dec_dir

    async def mount_state(self):  # noqa: ANN201
        from astrolol.plugins.guider.devices import MountState

        return MountState(dec=self.dec, pier_side=self.pier_side, slewing=self.slewing, tracking=self.tracking)

    async def pulse_guide(self, direction: str, duration_ms: int) -> None:
        if self.fail_pulses > 0:
            self.fail_pulses -= 1
            raise RuntimeError("pulse refused")
        self.pulses.append((direction, duration_ms))
        await asyncio.sleep(self.pulse_latency + duration_ms / 1000 * self.time_scale)  # a pulse takes (scaled) time
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
        amp, period = self.pe
        if amp:
            ra = self.matrix[:, 0] / max(float(np.hypot(*self.matrix[:, 0])), 1e-12)
            shift = shift + ra * amp * math.sin(2 * math.pi * t / period)
        return [(x + shift[0], y + shift[1]) for x, y, _ in self.stars]

    async def _produce(self, params: StreamParams) -> None:
        seq = 0
        roi = params.roi
        ox, oy = (roi.x, roi.y) if roi else (0, 0)
        h, w = (roi.height, roi.width) if roi else self.shape
        ys, xs = np.mgrid[0:h, 0:w]
        while True:
            await asyncio.sleep(params.exposure)
            if self.stalled:
                continue
            img = 100 + self.rng.normal(0, 3, (h, w))
            glitched, self._glitch = self._glitch > 0, max(self._glitch - 1, 0)
            smear = glitched and self.smear_frames > 0
            hidden = self.hidden or (glitched and self.lose_frames > 0)
            if not hidden:
                base_sx, sy = self.star_sigma
                sx = 8.0 if smear else base_sx  # motion during the exposure: long along x, and dimmer
                jitter = self.rng.normal(0, self.seeing_px, 2) if self.seeing_px else np.zeros(2)
                for (x, y), (_, _, amp) in zip(self.star_positions(), self.stars):
                    # Seeing moves the stars of a small field mostly together.
                    jx, jy = jitter + (self.rng.normal(0, self.seeing_px * 0.5, 2) if self.seeing_px else 0)
                    img += amp * (0.4 if smear else 1.0) * np.exp(
                        -((xs - (x + jx - ox)) ** 2 / (2 * sx**2) + (ys - (y + jy - oy)) ** 2 / (2 * sy**2))
                    )
            seq += 1
            self._broadcaster.publish(
                Frame(
                    pixels=np.clip(img, 0, self.max_adu).astype(np.uint16), seq=seq, timestamp=time.monotonic(),
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

    async def mount_state(self):  # noqa: ANN201
        return None if self.rig is None else await self.rig.mount_state()
