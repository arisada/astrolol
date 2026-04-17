"""Unit tests for dither logic in ImagerManager._loop_worker."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from astrolol.core.events import EventBus
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.devices.registry import DeviceRegistry
from astrolol.imaging import ImagerManager
from astrolol.imaging.models import DitherConfig, ExposureRequest

from tests.conftest import FakeCamera


@pytest.fixture()
def registry() -> DeviceRegistry:
    r = DeviceRegistry()
    r.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    return r


@pytest.fixture()
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def manager(registry: DeviceRegistry, event_bus: EventBus) -> DeviceManager:
    return DeviceManager(registry=registry, event_bus=event_bus)


@pytest.fixture()
def imager_manager(manager: DeviceManager, event_bus: EventBus, tmp_path: Path) -> ImagerManager:
    return ImagerManager(device_manager=manager, event_bus=event_bus, images_dir=tmp_path)


async def _connect(manager: DeviceManager, device_id: str = "cam1") -> str:
    config = DeviceConfig(device_id=device_id, kind="camera", adapter_key="fake_camera")
    return await manager.connect(config)


# ── Every-N-frames dithering ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dither_every_frame(imager_manager: ImagerManager, manager: DeviceManager) -> None:
    """_dither_fn is called before every frame after the first."""
    await _connect(manager)

    calls: list[DitherConfig] = []

    async def fake_dither(cfg: DitherConfig) -> None:
        calls.append(cfg)

    imager_manager._dither_fn = fake_dither  # type: ignore[assignment]
    dither_cfg = DitherConfig(every_frames=1, pixels=5.0)

    await imager_manager.start_loop(
        "cam1",
        ExposureRequest(duration=0.01, count=4, dither=dither_cfg),
    )
    task = imager_manager._imagers["cam1"]._loop_task
    if task:
        await asyncio.wait_for(task, timeout=5.0)

    # 4 frames → dither called before frames 2, 3, 4 (not before frame 1)
    assert len(calls) == 3
    assert all(c.pixels == 5.0 for c in calls)


@pytest.mark.asyncio
async def test_dither_every_3_frames(imager_manager: ImagerManager, manager: DeviceManager) -> None:
    """_dither_fn called once after every 3rd completed frame."""
    await _connect(manager)

    calls: list[DitherConfig] = []

    async def fake_dither(cfg: DitherConfig) -> None:
        calls.append(cfg)

    imager_manager._dither_fn = fake_dither  # type: ignore[assignment]
    dither_cfg = DitherConfig(every_frames=3, pixels=7.0)

    await imager_manager.start_loop(
        "cam1",
        ExposureRequest(duration=0.01, count=7, dither=dither_cfg),
    )
    task = imager_manager._imagers["cam1"]._loop_task
    if task:
        await asyncio.wait_for(task, timeout=5.0)

    # Frame counts after which dither fires: 3, 6 → 2 calls
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_no_dither_without_dither_fn(imager_manager: ImagerManager, manager: DeviceManager) -> None:
    """If _dither_fn is None, loop runs without error even when dither config is set."""
    await _connect(manager)

    imager_manager._dither_fn = None
    dither_cfg = DitherConfig(every_frames=1)

    await imager_manager.start_loop(
        "cam1",
        ExposureRequest(duration=0.01, count=3, dither=dither_cfg),
    )
    task = imager_manager._imagers["cam1"]._loop_task
    if task:
        await asyncio.wait_for(task, timeout=5.0)

    # No exception — loop completed normally


@pytest.mark.asyncio
async def test_no_dither_without_config(imager_manager: ImagerManager, manager: DeviceManager) -> None:
    """No dither when dither config is not included in the request."""
    await _connect(manager)

    calls: list[DitherConfig] = []

    async def fake_dither(cfg: DitherConfig) -> None:
        calls.append(cfg)

    imager_manager._dither_fn = fake_dither  # type: ignore[assignment]

    await imager_manager.start_loop(
        "cam1",
        ExposureRequest(duration=0.01, count=3),  # no dither
    )
    task = imager_manager._imagers["cam1"]._loop_task
    if task:
        await asyncio.wait_for(task, timeout=5.0)

    assert calls == []


@pytest.mark.asyncio
async def test_dither_failure_does_not_stop_loop(
    imager_manager: ImagerManager, manager: DeviceManager
) -> None:
    """A failing _dither_fn logs a warning but the loop continues."""
    await _connect(manager)

    call_count = 0

    async def failing_dither(cfg: DitherConfig) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("PHD2 dither failed")

    imager_manager._dither_fn = failing_dither  # type: ignore[assignment]
    dither_cfg = DitherConfig(every_frames=1)

    await imager_manager.start_loop(
        "cam1",
        ExposureRequest(duration=0.01, count=4, dither=dither_cfg),
    )
    task = imager_manager._imagers["cam1"]._loop_task
    if task:
        await asyncio.wait_for(task, timeout=5.0)

    # Dither was attempted for frames 2-4, loop ran to completion
    assert call_count == 3
