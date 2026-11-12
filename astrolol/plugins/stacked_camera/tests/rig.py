"""Fakes and a rig for testing the virtual cameras through the real device manager."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import astropy.io.fits as astropy_fits
import numpy as np
from fastapi import FastAPI

from astrolol.core.events import EventBus
from astrolol.core.plugin_api import PluginContext
from astrolol.devices.base.models import CameraStatus, DeviceState, ExposureParams, Image
from astrolol.devices.base.streaming import (
    Frame,
    FrameBroadcaster,
    FrameSubscription,
    StreamParams,
)
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.devices.registry import DeviceRegistry
from astrolol.plugins.stacked_camera import adapters
from astrolol.plugins.stacked_camera.adapters import FAST_KEY, STACKED_KEY
from astrolol.plugins.stacked_camera.plugin import get_plugin

SUB = 0.05


class SourceCamera:
    """A real camera as far as the plugin can tell: streams natively, frames on demand."""

    def __init__(self, **_: object) -> None:
        self._broadcaster = FrameBroadcaster()
        self.started: list[StreamParams] = []
        self.stops = 0
        self.streaming = False
        self.temperature: float | None = -10.0
        self.cooler: tuple[bool, float | None] | None = None
        self.alive = True
        self._seq = 0
        # Cards a probe exposure's FITS carries; None = the camera cannot expose when asked.
        self.probe_header: dict[str, object] | None = None
        self.probe_dir: Path | None = None
        self.exposures: list[float] = []

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def expose(self, params: ExposureParams) -> Image:
        # Only the probe may expose the real camera, and never while it streams.
        assert not self.streaming, "exposed while streaming"
        self.exposures.append(params.duration)
        if self.probe_header is None or self.probe_dir is None:
            raise RuntimeError("this camera does not expose")
        path = self.probe_dir / f"probe_{len(self.exposures)}.fits"
        hdu = astropy_fits.PrimaryHDU(np.zeros((4, 6), dtype=np.uint16))
        for key, value in self.probe_header.items():
            hdu.header[key] = value
        hdu.writeto(path)
        return Image(fits_path=str(path), width=6, height=4, exposure_duration=params.duration)

    async def abort(self) -> None:
        pass

    async def get_status(self) -> CameraStatus:
        return CameraStatus(state=DeviceState.CONNECTED, temperature=self.temperature)

    async def set_cooler(self, enabled: bool, target_temperature: float | None) -> None:
        self.cooler = (enabled, target_temperature)

    async def ping(self) -> bool:
        return self.alive

    async def start_stream(self, params: StreamParams) -> None:
        self.started.append(params)
        self.streaming = True

    async def stop_stream(self) -> None:
        self.stops += 1
        self.streaming = False
        self._broadcaster.end()

    def subscribe_frames(self) -> FrameSubscription:
        return self._broadcaster.subscribe()

    def emit(
        self,
        value: int = 100,
        exposure: float = SUB,
        age: float = 0.0,
        shape: tuple[int, int] = (6, 8),
        gain: int | None = None,
        binning: int = 1,
    ) -> None:
        self._seq += 1
        self._broadcaster.publish(
            Frame(
                pixels=np.full(shape, value, dtype=np.uint16),
                seq=self._seq,
                timestamp=time.monotonic() - age,
                exposure=exposure,
                gain=gain,
                binning=binning,
            )
        )

    def fail(self, error: Exception) -> None:
        self._broadcaster.end(error)


class PulsingSource(SourceCamera):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.pulses: list[tuple[str, int]] = []

    async def pulse_guide(self, direction: str, duration_ms: int) -> None:
        self.pulses.append((direction, duration_ms))


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.bus = EventBus()
        registry = DeviceRegistry()
        registry.register_camera("source", SourceCamera)
        registry.register_camera("pulsing_source", PulsingSource)
        self.manager = DeviceManager(registry, self.bus)
        self.app = FastAPI()
        self.plugin = get_plugin()
        ctx = PluginContext(
            event_bus=self.bus, device_manager=self.manager, device_registry=registry
        )
        with registry.registering_for("stacked_camera"):
            self.plugin.setup(self.app, ctx)
        self.hubs = self.app.state.stacked_camera_hubs
        self.hubs.sub_exposure = lambda: SUB
        self.registry = registry
        self.tmp_path = tmp_path

    async def connect(self, adapter: str, device_id: str, **params: object) -> object:
        await self.manager.connect(
            DeviceConfig(device_id=device_id, kind="camera", adapter_key=adapter, params=params)
        )
        return self.manager.get_camera(device_id)

    async def source(self, adapter: str = "source") -> SourceCamera:
        return await self.connect(adapter, "cam")  # type: ignore[return-value]

    async def stacked(self, source_id: str = "cam") -> adapters.StackedCamera:
        return await self.connect(STACKED_KEY, "cam_stack", source_id=source_id)  # type: ignore[return-value]

    async def fast(self, source_id: str = "cam") -> adapters.FastCamera:
        return await self.connect(FAST_KEY, "cam_fast", source_id=source_id)  # type: ignore[return-value]


async def feed(source: SourceCamera, count: int, **frame: object) -> None:
    """Deliver *count* subs at a real pace, as a camera would."""
    for _ in range(count):
        await asyncio.sleep(0.01)
        source.emit(**frame)  # type: ignore[arg-type]


async def started(source: SourceCamera) -> None:
    """Wait until the camera is streaming (the exposure has claimed the stream)."""
    for _ in range(500):
        if source.streaming:
            return
        await asyncio.sleep(0.002)
    raise AssertionError("the stream never started")
