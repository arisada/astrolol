"""Streaming for cameras that can't stream natively: back-to-back exposures as a frame stream."""

from __future__ import annotations

import asyncio
import contextlib
import time

import astropy.io.fits as astropy_fits
import numpy as np
import structlog

from astrolol.devices.base.interfaces import ICamera
from astrolol.devices.base.models import ExposureParams
from astrolol.devices.base.streaming import (
    Frame,
    FrameBroadcaster,
    FrameSubscription,
    StreamParams,
)

logger = structlog.get_logger()


def _read_pixels(fits_path: str) -> np.ndarray:
    data = astropy_fits.getdata(fits_path)
    if data.ndim != 2:
        raise ValueError(f"expected a 2-D image, got shape {data.shape}")
    return np.asarray(data)


class LoopingExposureStream:
    """``IStreamingCamera`` over any ``ICamera``: expose, read the frame, publish, repeat.

    Slower than a native stream (every frame goes through a FITS file and the driver's per
    exposure setup) but works with every camera. A region of interest is applied by cropping
    the full frame in software.
    """

    def __init__(self, camera: ICamera) -> None:
        self._camera = camera
        self._broadcaster = FrameBroadcaster()
        self._task: asyncio.Task[None] | None = None

    @property
    def streaming(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe_frames(self) -> FrameSubscription:
        return self._broadcaster.subscribe()

    async def start_stream(self, params: StreamParams) -> None:
        if self.streaming:
            raise RuntimeError("already streaming")
        self._task = asyncio.create_task(self._run(params))

    async def stop_stream(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # Whatever happened to the loop, subscribers must not wait forever.
        self._broadcaster.end()

    async def _run(self, params: StreamParams) -> None:
        request = ExposureParams(
            duration=params.exposure, gain=params.gain, binning=params.binning
        )
        seq = 0
        try:
            while True:
                image = await self._camera.expose(request)
                pixels = await asyncio.to_thread(_read_pixels, image.fits_path)
                origin = (0, 0)
                if params.roi is not None:
                    r = params.roi
                    pixels = pixels[r.y : r.y + r.height, r.x : r.x + r.width]
                    origin = (r.x, r.y)
                seq += 1
                self._broadcaster.publish(
                    Frame(
                        pixels=pixels,
                        seq=seq,
                        timestamp=time.monotonic(),
                        exposure=params.exposure,
                        gain=params.gain,
                        binning=params.binning,
                        origin=origin,
                    )
                )
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self._camera.abort()
            raise
        except Exception as exc:
            logger.error("stream.failed", error=str(exc), exc_info=True)
            self._broadcaster.end(exc)
