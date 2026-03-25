"""Shared fixtures and fake adapters for unit tests."""
import asyncio
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from astrolol.core.events import EventBus
from astrolol.devices.base.models import CameraStatus, DeviceState, ExposureParams, FocuserStatus, Image, MountStatus, SlewTarget
from astrolol.devices.manager import DeviceManager
from astrolol.devices.registry import DeviceRegistry
from astrolol.focuser import FocuserManager
from astrolol.imaging import ImagerManager
from astrolol.mount import MountManager


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


class FakeMount:
    """Minimal IMount implementation. Slew and park complete after a brief delay."""

    def __init__(self, **kwargs: object) -> None:
        self.connected = False
        self._ra: float = 0.0
        self._dec: float = 0.0
        self._tracking = False
        self._parked = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def slew(self, target: SlewTarget) -> None:
        await asyncio.sleep(0.05)
        self._ra = target.ra
        self._dec = target.dec
        self._parked = False

    async def stop(self) -> None:
        pass

    async def park(self) -> None:
        await asyncio.sleep(0.05)
        self._parked = True
        self._tracking = False

    async def unpark(self) -> None:
        self._parked = False

    async def sync(self, target: SlewTarget) -> None:
        self._ra = target.ra
        self._dec = target.dec

    async def set_tracking(self, enabled: bool) -> None:
        self._tracking = enabled

    async def get_status(self) -> MountStatus:
        state = DeviceState.CONNECTED if self.connected else DeviceState.DISCONNECTED
        return MountStatus(
            state=state,
            ra=self._ra,
            dec=self._dec,
            is_tracking=self._tracking,
            is_parked=self._parked,
        )

    async def ping(self) -> bool:
        return self.connected


class FakeFocuser:
    """Minimal IFocuser implementation. Moves complete after a brief delay."""

    def __init__(self, **kwargs: object) -> None:
        self.connected = False
        self._position: int = 5000

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def move_to(self, position: int) -> None:
        await asyncio.sleep(0.05)
        self._position = position

    async def move_by(self, steps: int) -> None:
        await asyncio.sleep(0.05)
        self._position = max(0, self._position + steps)

    async def halt(self) -> None:
        pass

    async def get_status(self) -> FocuserStatus:
        state = DeviceState.CONNECTED if self.connected else DeviceState.DISCONNECTED
        return FocuserStatus(state=state, position=self._position)

    async def ping(self) -> bool:
        return self.connected


@pytest.fixture
def registry() -> DeviceRegistry:
    r = DeviceRegistry()
    r.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    r.register_camera("failing_camera", FailingCamera)  # type: ignore[arg-type]
    r.register_mount("fake_mount", FakeMount)  # type: ignore[arg-type]
    r.register_focuser("fake_focuser", FakeFocuser)  # type: ignore[arg-type]
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


@pytest.fixture
def mount_manager(manager: DeviceManager, event_bus: EventBus) -> MountManager:
    return MountManager(device_manager=manager, event_bus=event_bus)


@pytest.fixture
def focuser_manager(manager: DeviceManager, event_bus: EventBus) -> FocuserManager:
    return FocuserManager(device_manager=manager, event_bus=event_bus)
