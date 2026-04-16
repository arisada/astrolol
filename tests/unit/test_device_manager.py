import pytest

from astrolol.core.errors import (
    AdapterNotFoundError,
    DeviceAlreadyConnectedError,
    DeviceConnectionError,
    DeviceKindError,
    DeviceNotFoundError,
)
from astrolol.core.events import DeviceConnected, DeviceDisconnected, DeviceStateChanged
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager


def camera_config(**kwargs: object) -> DeviceConfig:
    return DeviceConfig(kind="camera", adapter_key="fake_camera", **kwargs)  # type: ignore[arg-type]


# --- connect ---

@pytest.mark.asyncio
async def test_connect_success(manager: DeviceManager) -> None:
    device_id = await manager.connect(camera_config(device_id="cam1"))
    assert device_id == "cam1"
    assert len(manager.list_connected()) == 1


@pytest.mark.asyncio
async def test_connect_publishes_events(manager: DeviceManager, event_bus) -> None:
    q = event_bus.subscribe()
    await manager.connect(camera_config(device_id="cam1"))

    events = [await q.get() for _ in range(3)]
    types = [e.type for e in events]
    assert types == ["device.state_changed", "device.connected", "device.state_changed"]

    first, _, last = events
    assert first.old_state.value == "disconnected"  # type: ignore[attr-defined]
    assert first.new_state.value == "connecting"     # type: ignore[attr-defined]
    assert last.old_state.value == "connecting"      # type: ignore[attr-defined]
    assert last.new_state.value == "connected"       # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_connect_unknown_adapter(manager: DeviceManager) -> None:
    with pytest.raises(AdapterNotFoundError, match="no_such_adapter"):
        await manager.connect(DeviceConfig(kind="camera", adapter_key="no_such_adapter"))


@pytest.mark.asyncio
async def test_connect_duplicate_raises(manager: DeviceManager) -> None:
    await manager.connect(camera_config(device_id="cam1"))
    with pytest.raises(DeviceAlreadyConnectedError):
        await manager.connect(camera_config(device_id="cam1"))


@pytest.mark.asyncio
async def test_connect_hardware_failure_raises(manager: DeviceManager) -> None:
    config = DeviceConfig(kind="camera", adapter_key="failing_camera", device_id="bad_cam")
    with pytest.raises(DeviceConnectionError, match="Simulated hardware failure"):
        await manager.connect(config)


@pytest.mark.asyncio
async def test_connect_hardware_failure_publishes_error_state(manager: DeviceManager, event_bus) -> None:
    q = event_bus.subscribe()
    config = DeviceConfig(kind="camera", adapter_key="failing_camera", device_id="bad_cam")
    with pytest.raises(DeviceConnectionError):
        await manager.connect(config)

    events = [await q.get() for _ in range(2)]
    last = events[-1]
    assert last.type == "device.state_changed"          # type: ignore[attr-defined]
    assert last.new_state.value == "error"              # type: ignore[attr-defined]


# --- disconnect ---

@pytest.mark.asyncio
async def test_disconnect_success(manager: DeviceManager) -> None:
    await manager.connect(camera_config(device_id="cam1"))
    await manager.disconnect("cam1")
    assert manager.list_connected() == []


@pytest.mark.asyncio
async def test_disconnect_publishes_event(manager: DeviceManager, event_bus) -> None:
    q = event_bus.subscribe()
    await manager.connect(camera_config(device_id="cam1"))
    while not q.empty():
        await q.get()  # drain connect events

    await manager.disconnect("cam1")
    event = await q.get()
    assert isinstance(event, DeviceDisconnected)
    assert event.device_key == "cam1"


@pytest.mark.asyncio
async def test_disconnect_unknown_raises(manager: DeviceManager) -> None:
    with pytest.raises(DeviceNotFoundError):
        await manager.disconnect("ghost")


# --- get_camera / kind checking ---

@pytest.mark.asyncio
async def test_get_camera_returns_instance(manager: DeviceManager) -> None:
    await manager.connect(camera_config(device_id="cam1"))
    cam = manager.get_camera("cam1")
    assert cam is not None


@pytest.mark.asyncio
async def test_get_wrong_kind_raises(manager: DeviceManager) -> None:
    await manager.connect(camera_config(device_id="cam1"))
    with pytest.raises(DeviceKindError):
        manager.get_mount("cam1")


# --- singleton kind enforcement ---

def mount_config(device_id: str = "mount1", adapter_key: str = "fake_mount") -> DeviceConfig:
    return DeviceConfig(kind="mount", adapter_key=adapter_key, device_id=device_id)


@pytest.mark.asyncio
async def test_connecting_second_mount_evicts_first(manager: DeviceManager) -> None:
    await manager.connect(mount_config("mount1"))
    assert any(d["device_id"] == "mount1" for d in manager.list_connected())

    await manager.connect(mount_config("mount2"))

    ids = {d["device_id"] for d in manager.list_connected()}
    assert "mount1" not in ids
    assert "mount2" in ids


@pytest.mark.asyncio
async def test_singleton_eviction_publishes_disconnected_event(
    manager: DeviceManager, event_bus
) -> None:
    await manager.connect(mount_config("mount1"))
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await manager.connect(mount_config("mount2"))

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    # Drain any remaining events fired async
    import asyncio
    await asyncio.sleep(0)
    while not q.empty():
        events.append(q.get_nowait())

    types = [e.type for e in events]
    assert "device.disconnected" in types
    disconnected = next(e for e in events if e.type == "device.disconnected")
    assert disconnected.device_key == "mount1"


@pytest.mark.asyncio
async def test_two_focusers_can_coexist(manager: DeviceManager) -> None:
    """Focusers are not singletons — two can be connected simultaneously."""
    await manager.connect(DeviceConfig(kind="focuser", adapter_key="fake_focuser", device_id="foc1"))
    await manager.connect(DeviceConfig(kind="focuser", adapter_key="fake_focuser", device_id="foc2"))
    ids = {d["device_id"] for d in manager.list_connected()}
    assert {"foc1", "foc2"}.issubset(ids)


@pytest.mark.asyncio
async def test_same_mount_id_still_raises_already_connected(manager: DeviceManager) -> None:
    """Reconnecting the exact same device_id should still raise, not silently succeed."""
    await manager.connect(mount_config("mount1"))
    with pytest.raises(DeviceAlreadyConnectedError):
        await manager.connect(mount_config("mount1"))


# --- list_connected ---

@pytest.mark.asyncio
async def test_list_connected(manager: DeviceManager) -> None:
    await manager.connect(camera_config(device_id="cam1"))
    await manager.connect(camera_config(device_id="cam2"))
    listed = manager.list_connected()
    ids = {d["device_id"] for d in listed}
    assert ids == {"cam1", "cam2"}


# --- watchdog ---

@pytest.mark.asyncio
async def test_watchdog_task_started_on_connect(manager: DeviceManager) -> None:
    """A watchdog task is created when a device connects."""
    await manager.connect(camera_config(device_id="cam1"))
    entry = manager._devices["cam1"]
    assert entry._watchdog is not None
    assert not entry._watchdog.done()
    await manager.disconnect("cam1")


@pytest.mark.asyncio
async def test_watchdog_task_cancelled_on_disconnect(manager: DeviceManager) -> None:
    """Watchdog task is cancelled when device is disconnected."""
    await manager.connect(camera_config(device_id="cam1"))
    entry = manager._devices["cam1"]
    watchdog = entry._watchdog
    assert watchdog is not None
    assert not watchdog.done()

    await manager.disconnect("cam1")
    assert watchdog.done()


@pytest.mark.asyncio
async def test_watchdog_task_started_on_reconnect(manager: DeviceManager) -> None:
    """Watchdog is restarted after a reconnect."""
    await manager.connect(camera_config(device_id="cam1"))
    await manager.soft_disconnect("cam1")
    await manager.reconnect("cam1")
    entry = manager._devices["cam1"]
    assert entry._watchdog is not None
    assert not entry._watchdog.done()
    await manager.disconnect("cam1")


@pytest.mark.asyncio
async def test_watchdog_detects_failure(manager: DeviceManager, event_bus) -> None:
    """_watchdog_worker transitions device to ERROR when ping returns False."""
    import asyncio
    from astrolol.devices.base.models import DeviceState

    await manager.connect(camera_config(device_id="cam1"))
    entry = manager._devices["cam1"]
    entry.instance.connected = False  # make ping() return False

    q = event_bus.subscribe()
    # Run one watchdog cycle manually (bypass the sleep)
    entry2 = manager._devices.get("cam1")
    assert entry2 is not None
    ok = await asyncio.wait_for(entry2.instance.ping(), timeout=1.0)
    assert not ok
    entry2.state = DeviceState.ERROR
    await manager._publish_state_change(entry2.config, DeviceState.CONNECTED, DeviceState.ERROR)

    assert entry.state == DeviceState.ERROR
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    sc = next(e for e in events if e.type == "device.state_changed")
    assert sc.new_state.value == "error"


@pytest.mark.asyncio
async def test_watchdog_detects_recovery(manager: DeviceManager, event_bus) -> None:
    """_watchdog_worker transitions device back to CONNECTED when ping recovers."""
    import asyncio
    from astrolol.devices.base.models import DeviceState

    await manager.connect(camera_config(device_id="cam1"))
    entry = manager._devices["cam1"]
    entry.state = DeviceState.ERROR  # simulate prior failure

    q = event_bus.subscribe()
    # Simulate recovery
    ok = await asyncio.wait_for(entry.instance.ping(), timeout=1.0)
    assert ok
    entry.state = DeviceState.CONNECTED
    await manager._publish_state_change(entry.config, DeviceState.ERROR, DeviceState.CONNECTED)

    assert entry.state == DeviceState.CONNECTED
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    sc = next(e for e in events if e.type == "device.state_changed")
    assert sc.new_state.value == "connected"
