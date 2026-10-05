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

    _patch_fits_headers(fits_file, None, None, None, object_name="M42")

    with astrofits.open(str(fits_file)) as hdul:
        assert hdul[0].header["OBJECT"] == "M42"


def test_patch_fits_headers_no_object_when_empty(tmp_path: Path):
    from astropy.io import fits as astrofits
    from tests.conftest import make_fake_fits
    fits_file = make_fake_fits(tmp_path / "test.fits")

    _patch_fits_headers(fits_file, None, None, None, object_name="")

    with astrofits.open(str(fits_file)) as hdul:
        assert "OBJECT" not in hdul[0].header


def test_patch_fits_headers_writes_filter(tmp_path: Path):
    from astropy.io import fits as astrofits
    from tests.conftest import make_fake_fits
    fits_file = make_fake_fits(tmp_path / "test.fits")

    _patch_fits_headers(fits_file, None, None, None, filter_name="Ha")

    with astrofits.open(str(fits_file)) as hdul:
        assert hdul[0].header["FILTER"] == "Ha"


def test_patch_fits_headers_no_filter_when_empty(tmp_path: Path):
    from astropy.io import fits as astrofits
    from tests.conftest import make_fake_fits
    fits_file = make_fake_fits(tmp_path / "test.fits")

    _patch_fits_headers(fits_file, None, None, None, filter_name="")

    with astrofits.open(str(fits_file)) as hdul:
        assert "FILTER" not in hdul[0].header


# --- _do_expose on a tree-only profile (regression: object_name/filter_name/FITS
# telescope+site metadata used to only ever be looked up via the (now-removed) flat
# profile.devices list and profile.telescope field, which were always empty for a
# tree-only profile — dead for everything but the mount coord snapshot, which already
# had a tree fallback) ---

async def _tree_only_rig(manager: DeviceManager, tmp_path: Path):
    """site -> mount -> ota -> filter_wheel -> camera, all connected via the tree."""
    from astrolol.equipment.models import CameraItem, FilterWheelItem, MountItem, OTAItem, SiteItem
    from astrolol.equipment.store import EquipmentStore
    from astrolol.profiles.models import Profile, ProfileNode

    inv_store = EquipmentStore(tmp_path / "inventory.json")
    site = inv_store.create(SiteItem(name="Backyard", latitude=48.85, longitude=2.35, altitude=35.0))
    mount_item = inv_store.create(MountItem(name="Sim mount", adapter_key="fake_mount", connect_params={}))
    ota = inv_store.create(OTAItem(name="RedCat 51", focal_length=250.0, aperture=51.0))
    fw_item = inv_store.create(FilterWheelItem(
        name="EFW", adapter_key="fake_filter_wheel", connect_params={}, filter_names=["L", "R", "G", "B"],
    ))
    cam_item = inv_store.create(CameraItem(name="ASI2600", adapter_key="fake_camera", connect_params={}))

    await manager.connect(DeviceConfig(device_id="mount1", kind="mount", adapter_key="fake_mount"))
    await manager.connect(DeviceConfig(device_id="fw1", kind="filter_wheel", adapter_key="fake_filter_wheel"))
    await manager.connect(DeviceConfig(device_id="cam1", kind="camera", adapter_key="fake_camera"))

    profile = Profile(name="rig", roots=[ProfileNode(
        item_id=site.id, children=[ProfileNode(
            item_id=mount_item.id, children=[ProfileNode(
                item_id=ota.id, children=[ProfileNode(
                    item_id=fw_item.id, children=[ProfileNode(item_id=cam_item.id)],
                )],
            )],
        )],
    )])
    return inv_store, profile


@pytest.mark.asyncio
async def test_do_expose_tree_profile_patches_fits_headers_from_ota_and_site(
    manager: DeviceManager, event_bus, tmp_path: Path
) -> None:
    from astropy.coordinates import SkyCoord
    from astropy.io import fits as astrofits
    from astrolol.mount.manager import MountManager

    inv_store, profile = await _tree_only_rig(manager, tmp_path)
    mount_manager = MountManager(device_manager=manager, event_bus=event_bus)
    await mount_manager.set_target("mount1", SkyCoord(ra=83.8, dec=-5.4, unit="deg"), name="M42")

    imager_manager = ImagerManager(
        device_manager=manager, event_bus=event_bus, images_dir=tmp_path,
        equipment_store=inv_store, mount_manager=mount_manager,
    )
    imager_manager.set_context(profile)

    result = await imager_manager.expose("cam1", ExposureRequest(duration=1.0, save=False))

    with astrofits.open(result.fits_path) as hdul:
        hdr = hdul[0].header
        assert hdr["OBJECT"] == "M42"
        assert hdr["TELESCOP"] == "RedCat 51"
        assert hdr["FOCALLEN"] == 250.0
        assert hdr["APTDIA"] == 51.0
        assert hdr["SITELAT"] == 48.85
        assert hdr["SITELONG"] == 2.35
        assert hdr["SITEELEV"] == 35.0
        assert hdr["SITENAME"] == "Backyard"


@pytest.mark.asyncio
async def test_do_expose_tree_profile_resolves_filter_name_for_save_path(
    manager: DeviceManager, event_bus, tmp_path: Path
) -> None:
    """Regression: filter_name used to only ever be looked up via the (now-removed) flat
    profile.devices list, so it was always empty ("") for a tree-only profile — a dead
    %f filename token."""
    from astrolol.profiles.store import ProfileStore

    inv_store, profile = await _tree_only_rig(manager, tmp_path)
    await manager.get_filter_wheel("fw1").select_filter(2)  # "R" (1-indexed into filter_names)

    profile_store = ProfileStore(tmp_path / "profiles.json")
    profile_store.update_user_settings(
        profile_store.get_user_settings().model_copy(update={"save_filename_template": "%f_%N"})
    )

    imager_manager = ImagerManager(
        device_manager=manager, event_bus=event_bus, images_dir=tmp_path,
        equipment_store=inv_store, profile_store=profile_store,
    )
    imager_manager.set_context(profile)

    result = await imager_manager.expose("cam1", ExposureRequest(duration=1.0, save=True))

    assert Path(result.fits_path).name == "R_000001.fits"


@pytest.mark.asyncio
async def test_request_object_name_overrides_the_mount_target(
    manager: DeviceManager, event_bus, tmp_path: Path
) -> None:
    """A sequencer names frames after its task target, even when it didn't slew."""
    from astropy.coordinates import SkyCoord
    from astropy.io import fits as astrofits
    from astrolol.mount.manager import MountManager

    inv_store, profile = await _tree_only_rig(manager, tmp_path)
    mount_manager = MountManager(device_manager=manager, event_bus=event_bus)
    await mount_manager.set_target("mount1", SkyCoord(ra=83.8, dec=-5.4, unit="deg"), name="M42")
    imager_manager = ImagerManager(
        device_manager=manager, event_bus=event_bus, images_dir=tmp_path,
        equipment_store=inv_store, mount_manager=mount_manager,
    )
    imager_manager.set_context(profile)

    result = await imager_manager.expose(
        "cam1", ExposureRequest(duration=1.0, save=False, object_name="Horsehead")
    )
    with astrofits.open(result.fits_path) as hdul:
        assert hdul[0].header["OBJECT"] == "Horsehead"


@pytest.mark.asyncio
async def test_cancelled_expose_aborts_and_frees_the_camera(
    imager_manager: ImagerManager, manager: DeviceManager
) -> None:
    """Cancelling expose() (e.g. a sequencer "stop now") must not leave the camera EXPOSING."""
    await connected_camera(manager)
    camera = manager.get_camera("cam1")
    started = asyncio.Event()
    aborted: list[bool] = []

    async def slow_expose(params):  # type: ignore[no-untyped-def]
        started.set()
        await asyncio.sleep(10)

    async def abort() -> None:
        aborted.append(True)

    camera.expose = slow_expose  # type: ignore[method-assign]
    camera.abort = abort  # type: ignore[method-assign]

    task = asyncio.create_task(imager_manager.expose("cam1", ExposureRequest(duration=5.0)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert aborted == [True]
    assert imager_manager.get_status("cam1").state == ImagerState.IDLE


@pytest.mark.asyncio
async def test_expose_uses_persisted_per_camera_preview_settings(
    manager: DeviceManager, event_bus, tmp_path: Path
) -> None:
    """JPEG quality and stretch parameters saved via PUT /imager/{id}/settings must be
    picked up when generating the preview for the next exposure."""
    from astrolol.imaging.models import ImagerDeviceSettings
    from astrolol.profiles.store import ProfileStore

    await connected_camera(manager)
    profile_store = ProfileStore(tmp_path / "profiles.json")
    current = profile_store.get_user_settings()
    profile_store.update_user_settings(
        current.model_copy(update={
            "imager_settings": {
                "cam1": ImagerDeviceSettings(
                    jpeg_quality=40, stretch_target_bg=0.15, stretch_shadows_sigma=-1.0,
                ).model_dump(),
            },
        })
    )

    imager_manager = ImagerManager(device_manager=manager, event_bus=event_bus, images_dir=tmp_path, profile_store=profile_store)
    result = await imager_manager.expose("cam1", ExposureRequest(duration=1.0))
    stats = imager_manager.get_last_stats("cam1")

    assert Path(result.preview_path).exists()
    assert stats is not None
    # Black point at −1σ (not the default −2.8σ) below the displayed background.
    assert stats.display_sigma > 0
    assert stats.stretch_low == pytest.approx(stats.display_median - 1.0 * stats.display_sigma, rel=1e-4)
