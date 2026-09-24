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


class _AdapterWithDefaults:
    DEFAULT_CONNECT_PARAMS = {"port": "/dev/ttyUSB0"}


class _AdapterWithoutDefaults:
    pass


def test_adapters_for_kind():
    registry = DeviceRegistry()
    registry.register_mount("m", _AdapterWithDefaults)  # type: ignore[arg-type]
    assert registry.adapters_for_kind("mount") == {"m": _AdapterWithDefaults}
    assert registry.adapters_for_kind("unknown") == {}


def test_default_connect_params():
    registry = DeviceRegistry()
    registry.register_mount("with", _AdapterWithDefaults)  # type: ignore[arg-type]
    registry.register_mount("without", _AdapterWithoutDefaults)  # type: ignore[arg-type]
    assert registry.default_connect_params("mount", "with") == {"port": "/dev/ttyUSB0"}
    assert registry.default_connect_params("mount", "without") == {}


def test_default_connect_params_returns_a_copy():
    registry = DeviceRegistry()
    registry.register_mount("with", _AdapterWithDefaults)  # type: ignore[arg-type]
    registry.default_connect_params("mount", "with")["port"] = "mutated"
    assert _AdapterWithDefaults.DEFAULT_CONNECT_PARAMS == {"port": "/dev/ttyUSB0"}


def test_default_connect_params_unknown_adapter():
    import pytest
    with pytest.raises(KeyError):
        DeviceRegistry().default_connect_params("mount", "nope")
