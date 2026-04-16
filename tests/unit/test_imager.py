import asyncio
from pathlib import Path

import pytest

from astrolol.core.events import ExposureCompleted, ExposureFailed, ExposureStarted, LoopStarted, LoopStopped
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.imaging import ImagerManager
from astrolol.imaging.models import ExposureRequest, ImagerState


async def connected_camera(manager: DeviceManager, device_id: str = "cam1") -> str:
    config = DeviceConfig(device_id=device_id, kind="camera", adapter_key="fake_camera")
    return await manager.connect(config)


# --- single expose ---

@pytest.mark.asyncio
async def test_expose_returns_result(imager_manager: ImagerManager, manager: DeviceManager) -> None:
    await connected_camera(manager)
    result = await imager_manager.expose("cam1", ExposureRequest(duration=1.0))
    assert result.device_id == "cam1"
    assert result.fits_path.endswith(".fits")
    assert result.preview_path.endswith(".jpg")
    assert Path(result.preview_path).exists()


@pytest.mark.asyncio
async def test_expose_publishes_events(
    imager_manager: ImagerManager, manager: DeviceManager, event_bus
) -> None:
    await connected_camera(manager)
    q = event_bus.subscribe()
    # drain device connect events
    while not q.empty():
        await q.get()

    await imager_manager.expose("cam1", ExposureRequest(duration=0.5))

    events = [await q.get() for _ in range(2)]
    assert isinstance(events[0], ExposureStarted)
    assert isinstance(events[1], ExposureCompleted)
    assert events[0].device_id == "cam1"
    assert events[1].fits_path.endswith(".fits")


@pytest.mark.asyncio
async def test_expose_while_busy_raises(imager_manager: ImagerManager, manager: DeviceManager) -> None:
    await connected_camera(manager)
    await imager_manager.start_loop("cam1", ExposureRequest(duration=0.1))
    with pytest.raises(ValueError, match="busy"):
        await imager_manager.expose("cam1", ExposureRequest(duration=1.0))
    await imager_manager.stop_loop("cam1")


# --- loop ---

@pytest.mark.asyncio
async def test_loop_runs_multiple_exposures(
    imager_manager: ImagerManager, manager: DeviceManager, event_bus
) -> None:
    await connected_camera(manager)
    q = event_bus.subscribe()

    await imager_manager.start_loop("cam1", ExposureRequest(duration=0.01, count=3))

    # wait for the task to finish (count=3 means finite)
    task = imager_manager._imagers["cam1"]._loop_task
    if task:
        await asyncio.wait_for(task, timeout=5.0)

    all_events = []
    while not q.empty():
        all_events.append(q.get_nowait())
    completed = [e for e in all_events if isinstance(e, ExposureCompleted)]
    assert len(completed) == 3


@pytest.mark.asyncio
async def test_loop_stop(imager_manager: ImagerManager, manager: DeviceManager) -> None:
    await connected_camera(manager)
    await imager_manager.start_loop("cam1", ExposureRequest(duration=0.01))
    assert imager_manager.get_status("cam1").state == ImagerState.LOOPING
    await imager_manager.stop_loop("cam1")
    assert imager_manager.get_status("cam1").state == ImagerState.IDLE


@pytest.mark.asyncio
async def test_loop_publishes_started_stopped(
    imager_manager: ImagerManager, manager: DeviceManager, event_bus
) -> None:
    await connected_camera(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await imager_manager.start_loop("cam1", ExposureRequest(duration=0.01))
    started = await q.get()
    assert isinstance(started, LoopStarted)

    await imager_manager.stop_loop("cam1")
    # drain until LoopStopped
    while True:
        e = await asyncio.wait_for(q.get(), timeout=2.0)
        if isinstance(e, LoopStopped):
            break
    assert e.device_id == "cam1"


@pytest.mark.asyncio
async def test_stop_loop_when_not_looping_raises(
    imager_manager: ImagerManager, manager: DeviceManager
) -> None:
    await connected_camera(manager)
    with pytest.raises(ValueError, match="not looping"):
        await imager_manager.stop_loop("cam1")


# --- multiple cameras ---

@pytest.mark.asyncio
async def test_two_cameras_independent(
    imager_manager: ImagerManager, manager: DeviceManager
) -> None:
    await connected_camera(manager, "cam1")
    await connected_camera(manager, "cam2")

    await imager_manager.start_loop("cam1", ExposureRequest(duration=0.01))
    await imager_manager.start_loop("cam2", ExposureRequest(duration=0.01))

    assert imager_manager.get_status("cam1").state == ImagerState.LOOPING
    assert imager_manager.get_status("cam2").state == ImagerState.LOOPING

    await imager_manager.stop_loop("cam1")
    assert imager_manager.get_status("cam1").state == ImagerState.IDLE
    # cam2 may be LOOPING (between frames) or EXPOSING (in a frame) — not IDLE
    assert imager_manager.get_status("cam2").state != ImagerState.IDLE

    await imager_manager.stop_loop("cam2")
