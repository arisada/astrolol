"""Unit tests for FilterWheelManager."""
import pytest

from astrolol.core.events import EventBus, FilterWheelFilterChanged
from astrolol.devices.base.models import DeviceState
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.filter_wheel import FilterWheelManager


FILTER_WHEEL_CONFIG = DeviceConfig(
    device_id="test_fw",
    kind="filter_wheel",
    adapter_key="fake_filter_wheel",
)


@pytest.mark.asyncio
async def test_select_filter_passes_slot_to_adapter(filter_wheel_manager: FilterWheelManager, manager: DeviceManager) -> None:
    """select_filter passes the slot number to the underlying adapter."""
    await manager.connect(FILTER_WHEEL_CONFIG)
    fw = manager.get_filter_wheel("test_fw")

    await filter_wheel_manager.select_filter("test_fw", 3)

    status = await fw.get_status()
    assert status.current_slot == 3


@pytest.mark.asyncio
async def test_select_filter_publishes_event(filter_wheel_manager: FilterWheelManager, manager: DeviceManager, event_bus: EventBus) -> None:
    """select_filter publishes a FilterWheelFilterChanged event."""
    await manager.connect(FILTER_WHEEL_CONFIG)

    events = []
    q = event_bus.subscribe()

    await filter_wheel_manager.select_filter("test_fw", 2)

    # Drain the queue for the events
    while not q.empty():
        events.append(await q.get())

    fw_events = [e for e in events if isinstance(e, FilterWheelFilterChanged)]
    assert len(fw_events) == 1
    assert fw_events[0].device_id == "test_fw"
    assert fw_events[0].slot == 2


@pytest.mark.asyncio
async def test_select_filter_event_includes_filter_name(filter_wheel_manager: FilterWheelManager, manager: DeviceManager, event_bus: EventBus) -> None:
    """The FilterWheelFilterChanged event includes the filter name when available."""
    await manager.connect(FILTER_WHEEL_CONFIG)

    events = []
    q = event_bus.subscribe()

    await filter_wheel_manager.select_filter("test_fw", 1)

    while not q.empty():
        events.append(await q.get())

    fw_events = [e for e in events if isinstance(e, FilterWheelFilterChanged)]
    assert len(fw_events) == 1
    assert fw_events[0].filter_name == "L"  # FakeFilterWheel has ["L", "R", "G", "B"]


@pytest.mark.asyncio
async def test_select_filter_event_no_name_when_out_of_range(filter_wheel_manager: FilterWheelManager, manager: DeviceManager, event_bus: EventBus) -> None:
    """filter_name is None when the slot is beyond the filter_names list."""
    await manager.connect(FILTER_WHEEL_CONFIG)

    events = []
    q = event_bus.subscribe()

    # FakeFilterWheel has 4 filters; select slot 10 (out of range)
    await filter_wheel_manager.select_filter("test_fw", 10)

    while not q.empty():
        events.append(await q.get())

    fw_events = [e for e in events if isinstance(e, FilterWheelFilterChanged)]
    assert len(fw_events) == 1
    assert fw_events[0].filter_name is None


@pytest.mark.asyncio
async def test_get_status_returns_adapter_status(filter_wheel_manager: FilterWheelManager, manager: DeviceManager) -> None:
    """get_status returns the status from the underlying adapter."""
    await manager.connect(FILTER_WHEEL_CONFIG)

    status = await filter_wheel_manager.get_status("test_fw")

    assert status.state == DeviceState.CONNECTED
    assert status.filter_count == 4
    assert status.filter_names == ["L", "R", "G", "B"]
    assert status.is_moving is False


@pytest.mark.asyncio
async def test_get_status_raises_for_unknown_device(filter_wheel_manager: FilterWheelManager) -> None:
    """get_status raises DeviceNotFoundError for an unknown device_id."""
    from astrolol.core.errors import DeviceNotFoundError

    with pytest.raises(DeviceNotFoundError):
        await filter_wheel_manager.get_status("nonexistent_fw")


@pytest.mark.asyncio
async def test_select_filter_raises_for_unknown_device(filter_wheel_manager: FilterWheelManager) -> None:
    """select_filter raises DeviceNotFoundError for an unknown device_id."""
    from astrolol.core.errors import DeviceNotFoundError

    with pytest.raises(DeviceNotFoundError):
        await filter_wheel_manager.select_filter("nonexistent_fw", 1)


@pytest.mark.asyncio
async def test_get_status_raises_for_wrong_kind(filter_wheel_manager: FilterWheelManager, manager: DeviceManager) -> None:
    """get_status raises DeviceKindError when device exists but is not a filter_wheel."""
    from astrolol.core.errors import DeviceKindError

    camera_config = DeviceConfig(
        device_id="my_camera",
        kind="camera",
        adapter_key="fake_camera",
    )
    await manager.connect(camera_config)

    with pytest.raises(DeviceKindError):
        await filter_wheel_manager.get_status("my_camera")
