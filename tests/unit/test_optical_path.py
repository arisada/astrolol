"""Tests for astrolol.equipment.optical_path — the per-camera equipment tree resolver."""
from __future__ import annotations

import pytest

from astrolol.equipment.models import (
    CameraItem, FilterWheelItem, FocuserItem, MountItem, OTAItem, RotatorItem, SiteItem,
)
from astrolol.equipment.optical_path import (
    resolve_optical_paths,
    walk_mount_sites,
    walk_optical_paths,
)
from astrolol.equipment.store import EquipmentStore
from astrolol.profiles.models import Profile, ProfileNode
from tests.conftest import FakeCamera, FakeMount


@pytest.fixture
def inv_store(tmp_path):
    return EquipmentStore(tmp_path / "inventory.json")


def _site(inv_store):
    return inv_store.create(SiteItem(name="Backyard", latitude=48.85, longitude=2.35, altitude=35.0))


class _Entry:
    def __init__(self, kind, device_name, instance, device_id):
        self.config = type("cfg", (), {
            "kind": kind, "adapter_key": None,
            "params": {"device_name": device_name}, "device_id": device_id,
        })()
        self.instance = instance


class _FakeDM:
    def __init__(self, entries: dict):
        self._devices = {k: _Entry(*v, device_id=k) for k, v in entries.items()}

    def _get(self, device_id):
        return self._devices[device_id].instance

    get_mount = get_camera = get_focuser = get_filter_wheel = get_rotator = _get


def test_walk_optical_paths_single_camera_full_chain(inv_store):
    """site -> mount -> ota -> rotator -> focuser -> filter_wheel -> camera."""
    site = _site(inv_store)
    mount = inv_store.create(MountItem(name="EQ6-R"))
    ota = inv_store.create(OTAItem(name="RedCat 51", focal_length=250.0, aperture=51.0))
    rotator = inv_store.create(RotatorItem(name="Pyxis"))
    focuser = inv_store.create(FocuserItem(name="EAF"))
    fw = inv_store.create(FilterWheelItem(name="EFW", filter_names=["L", "R", "G", "B"]))
    cam = inv_store.create(CameraItem(name="ASI2600"))

    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount.id, children=[
            ProfileNode(item_id=ota.id, children=[
                ProfileNode(item_id=rotator.id, children=[
                    ProfileNode(item_id=focuser.id, children=[
                        ProfileNode(item_id=fw.id, children=[
                            ProfileNode(item_id=cam.id),
                        ]),
                    ]),
                ]),
            ]),
        ]),
    ])]

    paths = walk_optical_paths(roots, inv_store)
    assert len(paths) == 1
    path = paths[0]
    assert path.camera.id == cam.id
    assert path.mount.id == mount.id
    assert path.site.id == site.id
    assert path.ota.id == ota.id
    assert path.rotator.id == rotator.id
    assert path.focuser.id == focuser.id
    assert path.filter_wheel.id == fw.id


def test_walk_optical_paths_two_optical_paths_do_not_cross_contaminate(inv_store):
    """One mount, two OTAs (main + guide), each with its own camera/focuser/filter wheel —
    a guide camera must not inherit the main OTA's focuser/filter wheel or vice versa."""
    site = _site(inv_store)
    mount = inv_store.create(MountItem(name="EQ6-R"))

    main_ota = inv_store.create(OTAItem(name="Main", focal_length=500.0, aperture=80.0))
    main_focuser = inv_store.create(FocuserItem(name="Main focuser"))
    main_fw = inv_store.create(FilterWheelItem(name="Main EFW"))
    main_cam = inv_store.create(CameraItem(name="Main cam"))

    guide_ota = inv_store.create(OTAItem(name="Guide", focal_length=120.0, aperture=30.0))
    guide_cam = inv_store.create(CameraItem(name="Guide cam"))

    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount.id, children=[
            ProfileNode(item_id=main_ota.id, children=[
                ProfileNode(item_id=main_focuser.id, children=[
                    ProfileNode(item_id=main_fw.id, children=[
                        ProfileNode(item_id=main_cam.id),
                    ]),
                ]),
            ]),
            ProfileNode(item_id=guide_ota.id, children=[
                ProfileNode(item_id=guide_cam.id),
            ]),
        ]),
    ])]

    paths = walk_optical_paths(roots, inv_store)
    by_camera = {p.camera.id: p for p in paths}
    assert len(paths) == 2

    main_path = by_camera[main_cam.id]
    assert main_path.ota.id == main_ota.id
    assert main_path.focuser.id == main_focuser.id
    assert main_path.filter_wheel.id == main_fw.id
    assert main_path.mount.id == mount.id

    guide_path = by_camera[guide_cam.id]
    assert guide_path.ota.id == guide_ota.id
    assert guide_path.focuser is None
    assert guide_path.filter_wheel is None
    assert guide_path.mount.id == mount.id


def test_walk_optical_paths_missing_item_is_skipped_not_fatal(inv_store):
    cam = inv_store.create(CameraItem(name="Cam"))
    roots = [ProfileNode(item_id="gone", children=[ProfileNode(item_id=cam.id)])]
    paths = walk_optical_paths(roots, inv_store)
    assert len(paths) == 1
    assert paths[0].ota is None
    assert paths[0].mount is None


def test_walk_optical_paths_camera_with_no_ota_has_none_ancestors(inv_store):
    cam = inv_store.create(CameraItem(name="Cam"))
    roots = [ProfileNode(item_id=cam.id)]
    paths = walk_optical_paths(roots, inv_store)
    assert len(paths) == 1
    assert paths[0].ota is None
    assert paths[0].site is None
    assert paths[0].mount is None


def test_walk_mount_sites_finds_mount_without_any_camera(inv_store):
    """A mount needs no camera under it to be resolved — connect_tree_devices/
    _apply_tree_context push site+time to it regardless."""
    site = _site(inv_store)
    mount = inv_store.create(MountItem(name="EQ6-R"))
    roots = [ProfileNode(item_id=site.id, children=[ProfileNode(item_id=mount.id)])]

    result = walk_mount_sites(roots, inv_store)
    assert len(result) == 1
    found_mount, found_site = result[0]
    assert found_mount.id == mount.id
    assert found_site.id == site.id


def test_walk_mount_sites_mount_with_no_site_is_none(inv_store):
    mount = inv_store.create(MountItem(name="EQ6-R"))
    roots = [ProfileNode(item_id=mount.id)]
    [(found_mount, found_site)] = walk_mount_sites(roots, inv_store)
    assert found_mount.id == mount.id
    assert found_site is None


def test_resolve_optical_paths_fills_in_live_device_ids(inv_store):
    site = _site(inv_store)
    mount_item = inv_store.create(MountItem(name="EQ6-R", indi_device_name="EQ6-R Mount"))
    ota = inv_store.create(OTAItem(name="OTA", focal_length=500.0, aperture=80.0))
    cam_item = inv_store.create(CameraItem(name="Cam", indi_device_name="ZWO CCD ASI294MC Pro"))

    fake_mount = FakeMount()
    fake_camera = FakeCamera()
    dm = _FakeDM({
        "mount1": ("mount", "EQ6-R Mount", fake_mount),
        "cam1": ("camera", "ZWO CCD ASI294MC Pro", fake_camera),
    })

    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount_item.id, children=[
            ProfileNode(item_id=ota.id, children=[ProfileNode(item_id=cam_item.id)]),
        ]),
    ])]
    profile = Profile(name="p", roots=roots)

    [path] = resolve_optical_paths(profile, inv_store, dm)
    assert path.mount_device_id == "mount1"
    assert path.camera_device_id == "cam1"


def test_resolve_optical_paths_device_id_none_when_not_connected(inv_store):
    site = _site(inv_store)
    mount_item = inv_store.create(MountItem(name="EQ6-R", indi_device_name="EQ6-R Mount"))
    cam_item = inv_store.create(CameraItem(name="Cam", indi_device_name="ZWO CCD ASI294MC Pro"))
    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount_item.id, children=[ProfileNode(item_id=cam_item.id)]),
    ])]
    profile = Profile(name="p", roots=roots)
    dm = _FakeDM({})

    [path] = resolve_optical_paths(profile, inv_store, dm)
    assert path.mount_device_id is None
    assert path.camera_device_id is None
