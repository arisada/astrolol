"""Shared fixtures and fake adapters for unit tests."""
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from astrolol.core.events import EventBus
from astrolol.devices.base.models import CameraStatus, DeviceState, ExposureParams, Image
from astrolol.devices.manager import DeviceManager
from astrolol.devices.registry import DeviceRegistry
from astrolol.imaging import ImagerManager


def make_fake_fits(path: Path, width: int = 64, height: int = 64) -> Path:
    """Write a minimal FITS file with random pixel data."""
    data = np.random.randint(100, 4000, size=(height, width), dtype=np.uint16).astype(np.float32)
    hdu = fits.PrimaryHDU(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


class FakeCamera:
    """Minimal ICamera implementation. Connects instantly, writes a real FITS file on expose."""

    def __init__(self, images_dir: Path = Path("/tmp/astrolol_test"), **kwargs: object) -> None:
        self.connected = False
        self._images_dir = images_dir
        self._counter = 0

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def expose(self, params: ExposureParams) -> Image:
        self._counter += 1
        fits_path = self._images_dir / f"fake_{self._counter:04d}.fits"
        make_fake_fits(fits_path)
        return Image(
            fits_path=str(fits_path),
            width=64,
            height=64,
            exposure_duration=params.duration,
        )

    async def abort(self) -> None:
        pass

    async def get_status(self) -> CameraStatus:
        state = DeviceState.CONNECTED if self.connected else DeviceState.DISCONNECTED
        return CameraStatus(state=state)

    async def ping(self) -> bool:
        return self.connected


class FailingCamera:
    """Camera that always raises on connect — for error path tests."""

    def __init__(self, **kwargs: object) -> None:
        pass

    async def connect(self) -> None:
        raise RuntimeError("Simulated hardware failure")

    async def disconnect(self) -> None:
        pass

    async def expose(self, params: ExposureParams) -> Image:  # pragma: no cover
        raise NotImplementedError

    async def abort(self) -> None:
        pass

    async def get_status(self) -> CameraStatus:
        return CameraStatus(state=DeviceState.ERROR)

    async def ping(self) -> bool:
        return False


@pytest.fixture
def registry() -> DeviceRegistry:
    r = DeviceRegistry()
    r.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    r.register_camera("failing_camera", FailingCamera)  # type: ignore[arg-type]
    return r


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def manager(registry: DeviceRegistry, event_bus: EventBus) -> DeviceManager:
    return DeviceManager(registry=registry, event_bus=event_bus)


@pytest.fixture
def imager_manager(manager: DeviceManager, event_bus: EventBus, tmp_path: Path) -> ImagerManager:
    return ImagerManager(device_manager=manager, event_bus=event_bus, images_dir=tmp_path)
