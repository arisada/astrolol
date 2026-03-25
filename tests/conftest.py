"""Shared fixtures and fake adapters for unit tests."""
import pytest

from astrolol.core.events import EventBus
from astrolol.devices.base.models import CameraStatus, DeviceState, ExposureParams, Image
from astrolol.devices.manager import DeviceManager
from astrolol.devices.registry import DeviceRegistry


class FakeCamera:
    """Minimal ICamera implementation for tests. Connects instantly, never fails."""

    def __init__(self, **kwargs: object) -> None:
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def expose(self, params: ExposureParams) -> Image:
        return Image(fits_path="/tmp/fake.fits", width=1920, height=1080, exposure_duration=params.duration)

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
