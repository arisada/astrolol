import asyncio

import pytest

from astrolol.core.events import FocuserHalted, FocuserMoveCompleted, FocuserMoveStarted
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.focuser.manager import FocuserManager


async def connected_focuser(manager: DeviceManager, device_id: str = "foc1") -> str:
    config = DeviceConfig(device_id=device_id, kind="focuser", adapter_key="fake_focuser")
    return await manager.connect(config)


async def wait_for_move(focuser_manager: FocuserManager, device_id: str = "foc1") -> None:
    ctrl = focuser_manager._controllers.get(device_id)
    if ctrl and ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)


# --- move_to ---

@pytest.mark.asyncio
async def test_move_to_returns_immediately(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    await focuser_manager.move_to("foc1", 7000)
    # should not block


@pytest.mark.asyncio
async def test_move_to_reaches_target(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    await focuser_manager.move_to("foc1", 7000)
    await wait_for_move(focuser_manager)
    status = await focuser_manager.get_status("foc1")
    assert status.position == 7000


@pytest.mark.asyncio
async def test_move_to_publishes_events(
    focuser_manager: FocuserManager, manager: DeviceManager, event_bus
) -> None:
    await connected_focuser(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await focuser_manager.move_to("foc1", 6000)
    started = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(started, FocuserMoveStarted)
    assert started.target_position == 6000

    await wait_for_move(focuser_manager)
    completed = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(completed, FocuserMoveCompleted)
    assert completed.position == 6000


@pytest.mark.asyncio
async def test_move_to_while_busy_raises(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    await focuser_manager.move_to("foc1", 7000)
    with pytest.raises(ValueError, match="already moving"):
        await focuser_manager.move_to("foc1", 8000)
    await focuser_manager.halt("foc1")


# --- move_by ---

@pytest.mark.asyncio
async def test_move_by_positive(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    initial = (await focuser_manager.get_status("foc1")).position
    await focuser_manager.move_by("foc1", 500)
    await wait_for_move(focuser_manager)
    status = await focuser_manager.get_status("foc1")
    assert status.position == (initial or 0) + 500


@pytest.mark.asyncio
async def test_move_by_negative(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    await focuser_manager.move_to("foc1", 5000)
    await wait_for_move(focuser_manager)
    await focuser_manager.move_by("foc1", -200)
    await wait_for_move(focuser_manager)
    status = await focuser_manager.get_status("foc1")
    assert status.position == 4800


@pytest.mark.asyncio
async def test_move_by_clamps_at_zero(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    await focuser_manager.move_to("foc1", 100)
    await wait_for_move(focuser_manager)
    await focuser_manager.move_by("foc1", -9999)
    await wait_for_move(focuser_manager)
    status = await focuser_manager.get_status("foc1")
    assert status.position == 0


# --- halt ---

@pytest.mark.asyncio
async def test_halt_stops_move(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    await focuser_manager.move_to("foc1", 9000)
    await focuser_manager.halt("foc1")
    assert not focuser_manager._controllers["foc1"].is_busy


@pytest.mark.asyncio
async def test_halt_publishes_event(
    focuser_manager: FocuserManager, manager: DeviceManager, event_bus
) -> None:
    await connected_focuser(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await focuser_manager.move_to("foc1", 9000)
    await focuser_manager.halt("foc1")

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(isinstance(e, FocuserHalted) for e in events)


@pytest.mark.asyncio
async def test_halt_when_idle_is_safe(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    await focuser_manager.halt("foc1")  # should not raise


# --- status ---

@pytest.mark.asyncio
async def test_get_status(
    focuser_manager: FocuserManager, manager: DeviceManager
) -> None:
    await connected_focuser(manager)
    status = await focuser_manager.get_status("foc1")
    assert status.position is not None
    assert status.state.value == "connected"
