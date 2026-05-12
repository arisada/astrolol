import asyncio
from pathlib import Path

import pytest

from astrolol.core.events import ExposureCompleted, ExposureFailed, ExposureStarted, LoopStarted, LoopStopped
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.imaging import ImagerManager
from astrolol.imaging.imager import _expand_template, _patch_fits_headers
from astrolol.imaging.models import ExposureRequest, ImagerState


async def connected_camera(manager: DeviceManager, device_id: str = "cam1") -> str:
    config = DeviceConfig(device_id=device_id, kind="camera", adapter_key="fake_camera")
    return await manager.connect(config)


# --- single expose ---

@pytest.mark.asyncio
async def test_expose_no_save_uses_temp_path(
    imager_manager: ImagerManager, manager: DeviceManager, tmp_path: Path
) -> None:
    """Unsaved exposures must land in a deterministic temp path, not accumulate in images_dir."""
    await connected_camera(manager)
    result = await imager_manager.expose("cam1", ExposureRequest(duration=1.0, save=False))
    fits = Path(result.fits_path)
    # File must exist and be a valid FITS
    assert fits.exists()
    assert fits.suffix == ".fits"
    # Must NOT live inside the imager's images_dir (tmp_path in tests)
    assert not fits.is_relative_to(tmp_path)
    # Must be the deterministic per-device temp name
    assert fits.name == "temp_cam1.fits"
    # A second unsaved expose for the same camera overwrites the same path
    result2 = await imager_manager.expose("cam1", ExposureRequest(duration=1.0, save=False))
    assert result2.fits_path == result.fits_path


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


# --- _expand_template ---

def test_expand_template_counter_token():
    out = _expand_template("%N", "light", 7, 10.0, 100)
    assert out == "000007"


def test_expand_template_camera_name():
    out = _expand_template("%C", "light", 1, 1.0, 0, camera_name="zwo_asi294")
    assert out == "zwo_asi294"


def test_expand_template_filter_name():
    out = _expand_template("%f", "light", 1, 1.0, 0, filter_name="Ha")
    assert out == "Ha"


def test_expand_template_filter_empty_by_default():
    out = _expand_template("%f", "light", 1, 1.0, 0)
    assert out == ""


def test_expand_template_object_name():
    out = _expand_template("%O", "light", 1, 1.0, 0, object_name="M42")
    assert out == "M42"


def test_expand_template_object_falls_back_to_unknown():
    out = _expand_template("%O", "light", 1, 1.0, 0)
    assert out == "unknown"


def test_expand_template_gain_none():
    out = _expand_template("%G", "light", 1, 1.0, None)
    assert out == ""


def test_expand_template_full_path():
    out = _expand_template(
        "%O/%F_%N_%Es_%Gg_%C_%f",
        "light", 3, 60.0, 200,
        camera_name="cam1", filter_name="L", object_name="NGC7293",
    )
    assert out.startswith("NGC7293/")
    assert "light_000003_60.0s_200g_cam1_L" in out


# --- _patch_fits_headers OBJECT keyword ---

def test_patch_fits_headers_writes_object(tmp_path: Path):
    from astropy.io import fits as astrofits
    from tests.conftest import make_fake_fits
    fits_file = make_fake_fits(tmp_path / "test.fits")

    from astrolol.profiles.models import Profile
    profile = Profile(id="p1", name="test")
    _patch_fits_headers(fits_file, profile, None, object_name="M42")

    with astrofits.open(str(fits_file)) as hdul:
        assert hdul[0].header["OBJECT"] == "M42"


def test_patch_fits_headers_no_object_when_empty(tmp_path: Path):
    from astropy.io import fits as astrofits
    from tests.conftest import make_fake_fits
    fits_file = make_fake_fits(tmp_path / "test.fits")

    from astrolol.profiles.models import Profile
    profile = Profile(id="p1", name="test")
    _patch_fits_headers(fits_file, profile, None, object_name="")

    with astrofits.open(str(fits_file)) as hdul:
        assert "OBJECT" not in hdul[0].header
