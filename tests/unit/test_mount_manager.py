import asyncio

import pytest

from astrolol.core.events import (
    MountOperationFailed,
    MountParked,
    MountSlewAborted,
    MountSlewCompleted,
    MountSlewStarted,
    MountSynced,
    MountTrackingChanged,
    MountUnparked,
)
from astrolol.devices.base.models import SlewTarget, TrackingMode
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.mount.manager import MountManager


async def connected_mount(manager: DeviceManager, device_id: str = "mount1") -> str:
    config = DeviceConfig(device_id=device_id, kind="mount", adapter_key="fake_mount")
    return await manager.connect(config)


# --- slew ---

@pytest.mark.asyncio
async def test_slew_returns_immediately(mount_manager: MountManager, manager: DeviceManager) -> None:
    await connected_mount(manager)
    target = SlewTarget(ra=6.0, dec=45.0)
    await mount_manager.slew("mount1", target)
    # should not block — task runs in background
    status = await mount_manager.get_status("mount1")
    assert status.ra is not None


@pytest.mark.asyncio
async def test_slew_publishes_started_and_completed(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    target = SlewTarget(ra=6.0, dec=45.0)
    await mount_manager.slew("mount1", target)

    started = await asyncio.wait_for(q.get(), timeout=2.0)
    assert isinstance(started, MountSlewStarted)
    assert started.ra == 6.0

    # wait for background task to finish
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    completed = await asyncio.wait_for(q.get(), timeout=2.0)
    assert isinstance(completed, MountSlewCompleted)
    assert completed.dec == 45.0


@pytest.mark.asyncio
async def test_slew_updates_position(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    target = SlewTarget(ra=12.5, dec=-30.0)
    await mount_manager.slew("mount1", target)

    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    status = await mount_manager.get_status("mount1")
    assert status.ra == pytest.approx(12.5)
    assert status.dec == pytest.approx(-30.0)


@pytest.mark.asyncio
async def test_slew_while_busy_raises(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    await mount_manager.slew("mount1", SlewTarget(ra=1.0, dec=0.0))
    with pytest.raises(ValueError, match="busy"):
        await mount_manager.slew("mount1", SlewTarget(ra=2.0, dec=0.0))
    await mount_manager.stop("mount1")


# --- stop ---

@pytest.mark.asyncio
async def test_stop_aborts_slew(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.slew("mount1", SlewTarget(ra=1.0, dec=0.0))
    await mount_manager.stop("mount1")

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    types = [e.type for e in events]
    assert "mount.slew_aborted" in types


@pytest.mark.asyncio
async def test_stop_when_idle_is_safe(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    # Should not raise
    await mount_manager.stop("mount1")


# --- park / unpark ---

@pytest.mark.asyncio
async def test_park_publishes_parked_event(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.park("mount1")
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    assert any(isinstance(e, MountParked) for e in events)


@pytest.mark.asyncio
async def test_park_sets_parked_state(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    await mount_manager.park("mount1")
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    status = await mount_manager.get_status("mount1")
    assert status.is_parked is True


@pytest.mark.asyncio
async def test_unpark(mount_manager: MountManager, manager: DeviceManager) -> None:
    await connected_mount(manager)
    await mount_manager.park("mount1")
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    await mount_manager.unpark("mount1")
    status = await mount_manager.get_status("mount1")
    assert status.is_parked is False


# --- sync ---

@pytest.mark.asyncio
async def test_sync_publishes_event(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    target = SlewTarget(ra=5.5, dec=22.0)
    await mount_manager.sync("mount1", target)

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(event, MountSynced)
    assert event.ra == 5.5


# --- tracking ---

@pytest.mark.asyncio
async def test_set_tracking_publishes_event(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.set_tracking("mount1", True)
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(event, MountTrackingChanged)
    assert event.tracking is True

    status = await mount_manager.get_status("mount1")
    assert status.is_tracking is True


@pytest.mark.asyncio
async def test_disable_tracking(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    await mount_manager.set_tracking("mount1", True)
    await mount_manager.set_tracking("mount1", False)
    status = await mount_manager.get_status("mount1")
    assert status.is_tracking is False


@pytest.mark.asyncio
async def test_set_tracking_with_mode_event_carries_mode(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """MountTrackingChanged event should include the requested mode."""
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.set_tracking("mount1", True, TrackingMode.LUNAR)
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(event, MountTrackingChanged)
    assert event.tracking is True
    assert event.mode == TrackingMode.LUNAR


@pytest.mark.asyncio
async def test_set_tracking_mode_passed_to_adapter(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    """The adapter's set_tracking receives the mode value."""
    from tests.conftest import FakeMount
    await connected_mount(manager)
    fake: FakeMount = manager._devices["mount1"].instance  # type: ignore[union-attr]

    await mount_manager.set_tracking("mount1", True, TrackingMode.SOLAR)
    assert fake.last_tracking_mode == TrackingMode.SOLAR


@pytest.mark.asyncio
async def test_set_tracking_no_mode_passes_none(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    """Omitting mode passes None to the adapter (sidereal default stays with driver)."""
    from tests.conftest import FakeMount
    await connected_mount(manager)
    fake: FakeMount = manager._devices["mount1"].instance  # type: ignore[union-attr]

    await mount_manager.set_tracking("mount1", True)
    assert fake.last_tracking_mode is None


# --- unpark event ---

@pytest.mark.asyncio
async def test_unpark_publishes_event(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """unpark() should publish MountUnparked."""
    await connected_mount(manager)
    await mount_manager.park("mount1")
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.unpark("mount1")
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(event, MountUnparked)
    assert event.device_id == "mount1"


# --- operation_failed events ---

@pytest.mark.asyncio
async def test_slew_error_publishes_operation_failed(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """A slew that raises an exception publishes MountSlewAborted + MountOperationFailed."""
    from unittest.mock import patch

    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    async def failing_slew(_target):
        raise RuntimeError("motor fault")

    with patch.object(
        manager._devices["mount1"].instance, "slew", side_effect=failing_slew
    ):
        await mount_manager.slew("mount1", SlewTarget(ra=1.0, dec=0.0))
        ctrl = mount_manager._controllers["mount1"]
        if ctrl._active_task:
            await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    types = [e.type for e in events]
    assert "mount.slew_aborted" in types
    assert "mount.operation_failed" in types

    failed = next(e for e in events if isinstance(e, MountOperationFailed))
    assert failed.operation == "slew"
    assert "motor fault" in failed.reason


@pytest.mark.asyncio
async def test_slew_timeout_publishes_operation_failed(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """A slew that hits asyncio.TimeoutError publishes MountOperationFailed."""
    from unittest.mock import patch

    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    async def timing_out(_target):
        raise asyncio.TimeoutError()

    with patch.object(
        manager._devices["mount1"].instance, "slew", side_effect=timing_out
    ):
        await mount_manager.slew("mount1", SlewTarget(ra=1.0, dec=0.0))
        ctrl = mount_manager._controllers["mount1"]
        if ctrl._active_task:
            await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    failed = [e for e in events if isinstance(e, MountOperationFailed)]
    assert len(failed) == 1
    assert failed[0].operation == "slew"
    assert "timed out" in failed[0].reason


@pytest.mark.asyncio
async def test_park_error_publishes_operation_failed(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """An exception in park() should publish MountOperationFailed."""
    from unittest.mock import patch

    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    async def failing_park():
        raise RuntimeError("hardware fault")

    with patch.object(manager._devices["mount1"].instance, "park", side_effect=failing_park):
        await mount_manager.park("mount1")
        ctrl = mount_manager._controllers["mount1"]
        if ctrl._active_task:
            await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    failed = [e for e in events if isinstance(e, MountOperationFailed)]
    assert len(failed) == 1
    assert failed[0].operation == "park"
    assert "hardware fault" in failed[0].reason
