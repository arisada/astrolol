from unittest.mock import AsyncMock, MagicMock
from astrolol.devices.registry import DeviceRegistry
from astrolol.devices.base import ICamera, IMount


def make_mock_camera() -> type:
    """Return a class that satisfies ICamera Protocol."""
    cls = MagicMock()
    cls.connect = AsyncMock()
    cls.disconnect = AsyncMock()
    cls.expose = AsyncMock()
    cls.abort = AsyncMock()
    cls.get_status = AsyncMock()
    cls.ping = AsyncMock(return_value=True)
    return cls


def test_register_camera():
    registry = DeviceRegistry()
    mock_cls = make_mock_camera()
    registry.register_camera("mock_camera", mock_cls)
    assert "mock_camera" in registry.cameras
    assert registry.cameras["mock_camera"] is mock_cls


def test_all_keys():
    registry = DeviceRegistry()
    registry.register_camera("cam_a", make_mock_camera())
    keys = registry.all_keys()
    assert "cam_a" in keys["cameras"]
    assert keys["mounts"] == []
    assert keys["focusers"] == []
