"""Tests for ProfileStore and the /profiles API endpoints."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.api.profiles import (
    _apply_tree_context, _push_live_context, _find_mount_for_camera, find_profile_site,
    item_device_config, restore_last_profile,
)
from astrolol.equipment.models import CameraItem, MountItem, OTAItem, SiteItem
from astrolol.equipment.store import EquipmentStore
from astrolol.main import create_app
from astrolol.profiles.models import Profile, ProfileNode, Telescope
from astrolol.profiles.store import ProfileStore
from tests.conftest import FakeCamera, FakeMount, FakeFocuser


# ===========================================================================
# ProfileStore unit tests (no HTTP)
# ===========================================================================


@pytest.fixture
def store(tmp_path):
    return ProfileStore(tmp_path / "profiles.json")


def _profile(name: str = "test", **kwargs) -> Profile:
    return Profile(name=name, devices=[], **kwargs)


def test_empty_store_returns_no_profiles(store):
    assert store.list() == []


def test_create_profile(store):
    p = store.create(_profile(name="my rig"))
    assert p.name == "my rig"
    assert p.id  # UUID auto-assigned


def test_list_profiles(store):
    store.create(_profile(name="one"))
    store.create(_profile(name="two"))
    assert len(store.list()) == 2


def test_get_profile(store):
    p = store.create(_profile())
    assert store.get(p.id).id == p.id


def test_get_missing_raises(store):
    with pytest.raises(KeyError):
        store.get("does-not-exist")


def test_update_profile(store):
    p = store.create(_profile(name="original"))
    updated = Profile(id=p.id, name="updated", devices=[])
    result = store.update(updated)
    assert result.name == "updated"
    assert store.get(p.id).name == "updated"


def test_update_missing_raises(store):
    with pytest.raises(KeyError):
        store.update(_profile())


def test_delete_profile(store):
    p = store.create(_profile())
    store.delete(p.id)
    assert store.list() == []


def test_delete_missing_raises(store):
    with pytest.raises(KeyError):
        store.delete("does-not-exist")


def test_persistence(tmp_path):
    path = tmp_path / "profiles.json"
    s1 = ProfileStore(path)
    p = s1.create(_profile(name="persisted"))
    s2 = ProfileStore(path)
    assert s2.get(p.id).name == "persisted"


def test_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("not json {{{")
    store = ProfileStore(path)
    assert store.list() == []


def test_last_active_id_default_none(store):
    assert store.get_last_active_id() is None


def test_set_and_get_last_active_id(store):
    p = store.create(_profile())
    store.set_last_active_id(p.id)
    assert store.get_last_active_id() == p.id


def test_clear_last_active_id(store):
    p = store.create(_profile())
    store.set_last_active_id(p.id)
    store.set_last_active_id(None)
    assert store.get_last_active_id() is None


def test_last_active_id_persists_across_reload(tmp_path):
    path = tmp_path / "profiles.json"
    s1 = ProfileStore(path)
    p = s1.create(_profile())
    s1.set_last_active_id(p.id)
    s2 = ProfileStore(path)
    assert s2.get_last_active_id() == p.id


def test_old_file_without_last_active_key(tmp_path):
    """Backward compat: files that predate last_active_profile_id load fine."""
    path = tmp_path / "profiles.json"
    path.write_text('{"profiles": []}')
    store = ProfileStore(path)
    assert store.get_last_active_id() is None


# ===========================================================================
# API-level tests
# ===========================================================================


@pytest.fixture
def app(tmp_path):
    application = create_app()
    # Isolated profile store so tests never touch the real profiles.json
    application.state.profile_store = ProfileStore(tmp_path / "profiles.json")
    application.state.registry.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    application.state.registry.register_mount("fake_mount", FakeMount)  # type: ignore[arg-type]
    application.state.registry.register_focuser("fake_focuser", FakeFocuser)  # type: ignore[arg-type]
    return application


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30.0)


_PROFILE_BODY = {"name": "test rig", "devices": []}


@pytest.mark.asyncio
async def test_api_create_profile(client):
    async with client as c:
        r = await c.post("/profiles", json=_PROFILE_BODY)
    assert r.status_code == 201
    assert r.json()["name"] == "test rig"
    assert r.json()["id"]


@pytest.mark.asyncio
async def test_api_list_profiles(client):
    async with client as c:
        await c.post("/profiles", json=_PROFILE_BODY)
        await c.post("/profiles", json={**_PROFILE_BODY, "name": "rig 2"})
        r = await c.get("/profiles")
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_api_get_profile(client):
    async with client as c:
        created = (await c.post("/profiles", json=_PROFILE_BODY)).json()
        r = await c.get(f"/profiles/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_api_get_profile_404(client):
    async with client as c:
        r = await c.get("/profiles/nonexistent")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_update_profile(client):
    async with client as c:
        created = (await c.post("/profiles", json=_PROFILE_BODY)).json()
        r = await c.put(f"/profiles/{created['id']}", json={**created, "name": "renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"


@pytest.mark.asyncio
async def test_api_delete_profile(client):
    async with client as c:
        created = (await c.post("/profiles", json=_PROFILE_BODY)).json()
        r = await c.delete(f"/profiles/{created['id']}")
        assert r.status_code == 204
        r2 = await c.get("/profiles")
    assert r2.json() == []


@pytest.mark.asyncio
async def test_api_active_none_initially(client):
    async with client as c:
        r = await c.get("/profiles/active")
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_api_activate_profile(client):
    async with client as c:
        created = (await c.post("/profiles", json=_PROFILE_BODY)).json()
        r = await c.post(f"/profiles/{created['id']}/activate")
        assert r.status_code == 200
        assert r.json()["profile_id"] == created["id"]
        active = await c.get("/profiles/active")
    assert active.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_api_activate_persists_last_active_id(app, client):
    async with client as c:
        created = (await c.post("/profiles", json=_PROFILE_BODY)).json()
        await c.post(f"/profiles/{created['id']}/activate")
    assert app.state.profile_store.get_last_active_id() == created["id"]


@pytest.mark.asyncio
async def test_api_deactivate_clears_active(client):
    async with client as c:
        created = (await c.post("/profiles", json=_PROFILE_BODY)).json()
        await c.post(f"/profiles/{created['id']}/activate")
        r = await c.delete("/profiles/active")
        assert r.status_code == 204
        active = await c.get("/profiles/active")
    assert active.json() is None


@pytest.mark.asyncio
async def test_api_deactivate_clears_last_active_id(app, client):
    async with client as c:
        created = (await c.post("/profiles", json=_PROFILE_BODY)).json()
        await c.post(f"/profiles/{created['id']}/activate")
        await c.delete("/profiles/active")
    assert app.state.profile_store.get_last_active_id() is None


@pytest.mark.asyncio
async def test_api_activate_unknown_404(client):
    async with client as c:
        r = await c.post("/profiles/nonexistent/activate")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_activate_connects_devices(client):
    """Activating a profile connects all its devices (best-effort)."""
    profile_body = {
        "name": "with devices",
        "devices": [
            {
                "role": "camera",
                "config": {
                    "device_id": "cam1",
                    "kind": "camera",
                    "adapter_key": "fake_camera",
                    "params": {},
                },
            }
        ],
    }
    async with client as c:
        created = (await c.post("/profiles", json=profile_body)).json()
        result = (await c.post(f"/profiles/{created['id']}/activate")).json()
        assert any(d["device_id"] == "cam1" for d in result["connected"])
        connected = await c.get("/devices/connected")
    assert any(d["device_id"] == "cam1" for d in connected.json())


@pytest.mark.asyncio
async def test_api_deactivate_disconnects_devices(client):
    """Deactivating a profile disconnects all its devices."""
    profile_body = {
        "name": "with devices",
        "devices": [
            {
                "role": "camera",
                "config": {
                    "device_id": "cam1",
                    "kind": "camera",
                    "adapter_key": "fake_camera",
                    "params": {},
                },
            }
        ],
    }
    async with client as c:
        created = (await c.post("/profiles", json=profile_body)).json()
        await c.post(f"/profiles/{created['id']}/activate")
        await c.delete("/profiles/active")
        connected = await c.get("/devices/connected")
    assert connected.json() == []


# ===========================================================================
# Tree-context propagation (_apply_tree_context)
# ===========================================================================


@pytest.fixture
def inv_store(tmp_path):
    return EquipmentStore(tmp_path / "inventory.json")


def _fake_device_manager(entries: dict):
    """Minimal stand-in for DeviceManager._devices."""
    class _Entry:
        def __init__(self, kind, device_name, instance):
            self.config = type("cfg", (), {
                "kind": kind,
                "adapter_key": None,
                "params": {"device_name": device_name},
            })()
            self.instance = instance

    class _DM:
        def __init__(self):
            self._devices = {k: v for k, v in entries.items()}

    dm = _DM()
    dm._devices = {k: _Entry(*v) for k, v in entries.items()}
    return dm


def _fake_device_manager_generic(entries: dict):
    """Like _fake_device_manager, but entries are keyed by (kind, adapter_key, params)
    for adapters with no INDI-style device_name (e.g. plugins/eqmod's eqmod_sim)."""
    class _Entry:
        def __init__(self, kind, adapter_key, params, instance):
            self.config = type("cfg", (), {
                "kind": kind,
                "adapter_key": adapter_key,
                "params": params,
            })()
            self.instance = instance

    class _DM:
        pass

    dm = _DM()
    dm._devices = {k: _Entry(*v) for k, v in entries.items()}
    return dm


@pytest.mark.asyncio
async def test_tree_context_pushes_location_to_mount(inv_store):
    site = inv_store.create(SiteItem(
        name="Backyard", latitude=48.85, longitude=2.35, altitude=35.0,
    ))
    mount_item = inv_store.create(MountItem(
        name="EQ6-R", indi_device_name="EQ6-R Mount",
    ))

    fake_mount = FakeMount()
    dm = _fake_device_manager({"mount1": ("mount", "EQ6-R Mount", fake_mount)})

    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount_item.id),
    ])]
    await _apply_tree_context(roots, inv_store, dm)

    assert hasattr(fake_mount, "location")
    assert fake_mount.location == (48.85, 2.35, 35.0)


@pytest.mark.asyncio
async def test_tree_context_pushes_scope_info_to_camera(inv_store):
    ota = inv_store.create(OTAItem(
        name="RedCat 51", focal_length=250.0, aperture=51.0,
    ))
    cam_item = inv_store.create(CameraItem(
        name="ASI2600", indi_device_name="ZWO CCD ASI2600MC Pro",
    ))

    fake_camera = FakeCamera()
    dm = _fake_device_manager({"cam1": ("camera", "ZWO CCD ASI2600MC Pro", fake_camera)})

    roots = [ProfileNode(item_id=ota.id, children=[
        ProfileNode(item_id=cam_item.id),
    ])]
    await _apply_tree_context(roots, inv_store, dm)

    assert hasattr(fake_camera, "scope_info")
    assert fake_camera.scope_info == (250.0, 51.0)


@pytest.mark.asyncio
async def test_tree_context_propagates_through_mount(inv_store):
    """site → mount → ota → camera: scope info still reaches camera."""
    site = inv_store.create(SiteItem(
        name="Backyard", latitude=48.85, longitude=2.35, altitude=35.0,
    ))
    mount_item = inv_store.create(MountItem(name="EQ6-R", indi_device_name="EQ6-R Mount"))
    ota = inv_store.create(OTAItem(name="OTA", focal_length=500.0, aperture=80.0))
    cam_item = inv_store.create(CameraItem(name="Cam", indi_device_name="ZWO CCD ASI294MC Pro"))

    fake_mount = FakeMount()
    fake_camera = FakeCamera()
    dm = _fake_device_manager({
        "mount1": ("mount", "EQ6-R Mount", fake_mount),
        "cam1": ("camera", "ZWO CCD ASI294MC Pro", fake_camera),
    })

    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount_item.id, children=[
            ProfileNode(item_id=ota.id, children=[
                ProfileNode(item_id=cam_item.id),
            ]),
        ]),
    ])]
    await _apply_tree_context(roots, inv_store, dm)

    assert fake_mount.location == (48.85, 2.35, 35.0)
    assert fake_camera.scope_info == (500.0, 80.0)


@pytest.mark.asyncio
async def test_tree_context_missing_inventory_item_skipped(inv_store):
    """A node whose item_id is missing from inventory is silently skipped."""
    roots = [ProfileNode(item_id="no-such-id")]
    dm = _fake_device_manager({})
    # Should not raise
    await _apply_tree_context(roots, inv_store, dm)


@pytest.mark.asyncio
async def test_tree_context_matches_non_indi_adapter_by_key_and_params(inv_store):
    """A mount with no indi_device_name (e.g. plugins/eqmod's eqmod_sim) matches by
    adapter_key + connect_params instead — see _find_device_for_item."""
    site = inv_store.create(SiteItem(
        name="Backyard", latitude=48.85, longitude=2.35, altitude=35.0,
    ))
    mount_item = inv_store.create(MountItem(
        name="EQMOD Sim", adapter_key="eqmod_sim", connect_params={"state_key": "rig1"},
    ))

    fake_mount = FakeMount()
    dm = _fake_device_manager_generic({
        "m1": ("mount", "eqmod_sim", {"state_key": "rig1"}, fake_mount),
    })

    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount_item.id),
    ])]
    await _apply_tree_context(roots, inv_store, dm)

    assert fake_mount.location == (48.85, 2.35, 35.0)


@pytest.mark.asyncio
async def test_tree_context_generic_adapter_params_mismatch_is_noop(inv_store):
    """Same adapter_key but different connect_params must not match — this is the
    only identity signal available for a non-INDI adapter, so it must be exact."""
    site = inv_store.create(SiteItem(
        name="Backyard", latitude=48.85, longitude=2.35, altitude=35.0,
    ))
    mount_item = inv_store.create(MountItem(
        name="EQMOD Sim", adapter_key="eqmod_sim", connect_params={"state_key": "rig1"},
    ))

    fake_mount = FakeMount()
    dm = _fake_device_manager_generic({
        "m1": ("mount", "eqmod_sim", {"state_key": "rig2"}, fake_mount),
    })

    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount_item.id),
    ])]
    await _apply_tree_context(roots, inv_store, dm)  # should not raise

    assert not hasattr(fake_mount, "location")


@pytest.mark.asyncio
async def test_tree_context_no_matching_device_is_noop(inv_store):
    """If the inventory item has no matching connected device, nothing breaks."""
    mount_item = inv_store.create(MountItem(name="EQ6-R", indi_device_name="EQ6-R Mount"))
    site = inv_store.create(SiteItem(
        name="Backyard", latitude=48.85, longitude=2.35, altitude=35.0,
    ))
    dm = _fake_device_manager({})  # no devices connected

    roots = [ProfileNode(item_id=site.id, children=[
        ProfileNode(item_id=mount_item.id),
    ])]
    await _apply_tree_context(roots, inv_store, dm)  # should not raise


# ===========================================================================
# Live context propagation (_push_live_context, _find_mount_for_camera)
# ===========================================================================


@pytest.mark.asyncio
async def test_push_live_context_sends_coords_to_camera(inv_store):
    """mount → camera: live RA/Dec pushed to camera's push_telescope_coord."""
    mount_item = inv_store.create(MountItem(name="EQ6-R", indi_device_name="EQ6-R Mount"))
    cam_item = inv_store.create(CameraItem(name="ASI2600", indi_device_name="ZWO CCD ASI2600MC Pro"))

    fake_mount = FakeMount()
    fake_mount._ra = 5.5
    fake_mount._dec = -20.0
    fake_camera = FakeCamera()
    dm = _fake_device_manager({
        "mount1": ("mount", "EQ6-R Mount", fake_mount),
        "cam1": ("camera", "ZWO CCD ASI2600MC Pro", fake_camera),
    })

    roots = [ProfileNode(item_id=mount_item.id, children=[
        ProfileNode(item_id=cam_item.id),
    ])]
    await _push_live_context(roots, inv_store, dm)

    assert hasattr(fake_camera, "telescope_coord")
    ra_jnow, dec_jnow = fake_camera.telescope_coord
    # Values should be close to what FakeMount.get_status() returns (JNow coords)
    assert abs(ra_jnow - 5.5) < 0.1
    assert abs(dec_jnow - (-20.0)) < 0.1


@pytest.mark.asyncio
async def test_push_live_context_no_camera_without_mount(inv_store):
    """A camera with no mount ancestor does not receive a coord push."""
    cam_item = inv_store.create(CameraItem(name="ASI2600", indi_device_name="ZWO CCD ASI2600MC Pro"))

    fake_camera = FakeCamera()
    dm = _fake_device_manager({
        "cam1": ("camera", "ZWO CCD ASI2600MC Pro", fake_camera),
    })

    roots = [ProfileNode(item_id=cam_item.id)]
    await _push_live_context(roots, inv_store, dm)

    assert not hasattr(fake_camera, "telescope_coord")


@pytest.mark.asyncio
async def test_push_live_context_missing_item_skipped(inv_store):
    """A node with a missing inventory item does not prevent the rest from running."""
    mount_item = inv_store.create(MountItem(name="EQ6-R", indi_device_name="EQ6-R Mount"))
    cam_item = inv_store.create(CameraItem(name="ASI2600", indi_device_name="ZWO CCD ASI2600MC Pro"))

    fake_mount = FakeMount()
    fake_camera = FakeCamera()
    dm = _fake_device_manager({
        "mount1": ("mount", "EQ6-R Mount", fake_mount),
        "cam1": ("camera", "ZWO CCD ASI2600MC Pro", fake_camera),
    })

    roots = [
        ProfileNode(item_id="no-such-id"),
        ProfileNode(item_id=mount_item.id, children=[ProfileNode(item_id=cam_item.id)]),
    ]
    await _push_live_context(roots, inv_store, dm)  # should not raise
    assert hasattr(fake_camera, "telescope_coord")


def test_find_mount_for_camera_returns_adapter(inv_store):
    """_find_mount_for_camera finds the ancestor mount for a given camera INDI name."""
    mount_item = inv_store.create(MountItem(name="EQ6-R", indi_device_name="EQ6-R Mount"))
    cam_item = inv_store.create(CameraItem(name="ASI2600", indi_device_name="ZWO CCD ASI2600MC Pro"))

    fake_mount = FakeMount()
    dm = _fake_device_manager({"mount1": ("mount", "EQ6-R Mount", fake_mount)})

    roots = [ProfileNode(item_id=mount_item.id, children=[ProfileNode(item_id=cam_item.id)])]
    result = _find_mount_for_camera(roots, inv_store, dm, "ZWO CCD ASI2600MC Pro")
    assert result is fake_mount


def test_find_mount_for_camera_returns_none_when_no_ancestor(inv_store):
    """Returns None if the camera has no mount ancestor in the tree."""
    cam_item = inv_store.create(CameraItem(name="ASI2600", indi_device_name="ZWO CCD ASI2600MC Pro"))
    dm = _fake_device_manager({})

    roots = [ProfileNode(item_id=cam_item.id)]
    result = _find_mount_for_camera(roots, inv_store, dm, "ZWO CCD ASI2600MC Pro")
    assert result is None


def test_find_mount_for_camera_wrong_name_returns_none(inv_store):
    """Returns None when asked for a camera INDI name that is not in the tree."""
    mount_item = inv_store.create(MountItem(name="EQ6-R", indi_device_name="EQ6-R Mount"))
    cam_item = inv_store.create(CameraItem(name="ASI2600", indi_device_name="ZWO CCD ASI2600MC Pro"))
    fake_mount = FakeMount()
    dm = _fake_device_manager({"mount1": ("mount", "EQ6-R Mount", fake_mount)})

    roots = [ProfileNode(item_id=mount_item.id, children=[ProfileNode(item_id=cam_item.id)])]
    result = _find_mount_for_camera(roots, inv_store, dm, "Some Other Camera")
    assert result is None


# ===========================================================================
# Site lookup in the profile tree (find_profile_site)
# ===========================================================================


def _site(inv_store):
    return inv_store.create(SiteItem(name="Backyard", latitude=48.85, longitude=2.35, altitude=35.0))


def test_find_profile_site_at_root(inv_store):
    site = _site(inv_store)
    profile = Profile(name="p", roots=[ProfileNode(item_id=site.id)])
    assert find_profile_site(profile, inv_store) == site


def test_find_profile_site_nested(inv_store):
    ota = inv_store.create(OTAItem(name="OTA", focal_length=500.0, aperture=80.0))
    site = _site(inv_store)
    profile = Profile(name="p", roots=[ProfileNode(item_id=ota.id, children=[ProfileNode(item_id=site.id)])])
    assert find_profile_site(profile, inv_store) == site


def test_find_profile_site_skips_missing_items(inv_store):
    site = _site(inv_store)
    profile = Profile(name="p", roots=[ProfileNode(item_id="gone"), ProfileNode(item_id=site.id)])
    assert find_profile_site(profile, inv_store) == site


def test_find_profile_site_none(inv_store):
    mount = inv_store.create(MountItem(name="EQ6-R"))
    assert find_profile_site(Profile(name="p", roots=[ProfileNode(item_id=mount.id)]), inv_store) is None
    assert find_profile_site(Profile(name="p"), inv_store) is None


@pytest.mark.asyncio
async def test_connecting_a_mount_pushes_the_active_profile_site(app, client, tmp_path):
    """Regression: /devices/connect read a removed Profile.location field and never pushed the site."""
    inv_store = EquipmentStore(tmp_path / "inventory.json")
    app.state.equipment_store = inv_store
    site = _site(inv_store)
    app.state.active_profile = Profile(name="p", roots=[ProfileNode(item_id=site.id)])

    async with client as c:
        r = await c.post("/devices/connect", json={"device_id": "m1", "kind": "mount", "adapter_key": "fake_mount"})
    assert r.status_code == 201
    assert app.state.device_manager.get_mount("m1").location == (48.85, 2.35, 35.0)


# ===========================================================================
# Connecting the equipment tree (activation + startup restore)
# ===========================================================================


def test_item_device_config_native_adapter(inv_store):
    item = inv_store.create(MountItem(name="AZ-EQ6", adapter_key="eqmod", connect_params={"port": "/dev/ttyUSB0"}))
    config = item_device_config(item)
    assert (config.device_id, config.kind, config.adapter_key) == ("mount_az_eq6", "mount", "eqmod")
    assert config.params == {"port": "/dev/ttyUSB0"}


def test_item_device_config_indi(inv_store):
    item = inv_store.create(CameraItem(name="ASI2600", indi_driver="indi_asi_ccd", indi_device_name="ZWO CCD ASI2600MC Pro"))
    config = item_device_config(item)
    assert config.adapter_key == "indi_camera"
    assert config.params == {"device_name": "ZWO CCD ASI2600MC Pro", "executable": "indi_asi_ccd"}


def test_item_device_config_none_without_connection_info(inv_store):
    assert item_device_config(inv_store.create(MountItem(name="bare"))) is None
    assert item_device_config(_site(inv_store)) is None
    assert item_device_config(inv_store.create(OTAItem(name="OTA", focal_length=500.0, aperture=80.0))) is None


def test_item_device_config_id_is_stable_and_falls_back_to_item_id(inv_store):
    item = inv_store.create(MountItem(name="!!!", adapter_key="fake_mount"))
    assert item_device_config(item).device_id == f"mount_{item.id[:8]}"
    assert item_device_config(item).device_id == item_device_config(item).device_id


def _tree_profile(inv_store, *items):
    site = _site(inv_store)
    return Profile(name="rig", roots=[ProfileNode(item_id=site.id, children=[ProfileNode(item_id=i.id) for i in items])])


@pytest.mark.asyncio
async def test_activate_connects_tree_devices_and_pushes_the_site(app, client, tmp_path):
    inv_store = EquipmentStore(tmp_path / "inventory.json")
    app.state.equipment_store = inv_store
    mount = inv_store.create(MountItem(name="Sim mount", adapter_key="fake_mount", connect_params={}))
    profile = app.state.profile_store.create(_tree_profile(inv_store, mount))

    async with client as c:
        r = await c.post(f"/profiles/{profile.id}/activate")
    assert r.status_code == 200
    assert [d["device_id"] for d in r.json()["connected"]] == ["mount_sim_mount"]
    assert app.state.device_manager.get_mount("mount_sim_mount").location == (48.85, 2.35, 35.0)


@pytest.mark.asyncio
async def test_activate_does_not_reconnect_a_device_already_connected_by_the_wizard(app, client, tmp_path):
    inv_store = EquipmentStore(tmp_path / "inventory.json")
    app.state.equipment_store = inv_store
    mount = inv_store.create(MountItem(name="Sim mount", adapter_key="fake_mount", connect_params={}))
    profile = app.state.profile_store.create(_tree_profile(inv_store, mount))

    async with client as c:
        await c.post("/devices/connect", json={"device_id": "wizard_mount", "kind": "mount", "adapter_key": "fake_mount"})
        r = await c.post(f"/profiles/{profile.id}/activate")
    assert [d["device_id"] for d in r.json()["connected"]] == ["wizard_mount"]
    assert [d["device_id"] for d in app.state.device_manager.list_connected()] == ["wizard_mount"]


@pytest.mark.asyncio
async def test_activate_reports_tree_devices_that_fail_to_connect(app, client, tmp_path):
    inv_store = EquipmentStore(tmp_path / "inventory.json")
    app.state.equipment_store = inv_store
    mount = inv_store.create(MountItem(name="Ghost", adapter_key="no_such_adapter", connect_params={}))
    profile = app.state.profile_store.create(_tree_profile(inv_store, mount))

    async with client as c:
        r = await c.post(f"/profiles/{profile.id}/activate")
    assert r.status_code == 200
    assert [d["device_id"] for d in r.json()["failed"]] == ["mount_ghost"]


@pytest.mark.asyncio
async def test_restore_last_profile_reconnects_the_tree(tmp_path):
    """Regression: after a restart the profile's mount was forgotten and needed the wizard again."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from astrolol.core.events import EventBus
    from astrolol.devices.manager import DeviceManager
    from astrolol.devices.registry import DeviceRegistry
    from astrolol.mount.manager import MountManager

    inv_store = EquipmentStore(tmp_path / "inventory.json")
    profile_store = ProfileStore(tmp_path / "profiles.json")
    mount = inv_store.create(MountItem(name="Sim mount", adapter_key="fake_mount", connect_params={}))
    profile = _tree_profile(inv_store, mount)
    profile.roots.append(ProfileNode(item_id="deleted-item"))  # must not abort the restore
    profile = profile_store.create(profile)
    profile_store.set_last_active_id(profile.id)

    registry = DeviceRegistry()
    registry.register_mount("fake_mount", FakeMount)  # type: ignore[arg-type]
    bus = EventBus()
    device_manager = DeviceManager(registry=registry, event_bus=bus)
    mount_manager = MountManager(device_manager=device_manager, event_bus=bus)
    state = SimpleNamespace(
        profile_store=profile_store, equipment_store=inv_store, device_manager=device_manager,
        mount_manager=mount_manager, imager_manager=MagicMock(push_scope_info=AsyncMock()),
        active_profile=None,
    )

    await restore_last_profile(state)

    assert state.active_profile.id == profile.id
    restored = device_manager.get_mount("mount_sim_mount")
    assert restored.location == (48.85, 2.35, 35.0)
    for task in mount_manager._automation_tasks.values():
        task.cancel()


@pytest.mark.asyncio
async def test_restore_last_profile_without_last_profile_is_a_noop(tmp_path):
    from types import SimpleNamespace

    state = SimpleNamespace(profile_store=ProfileStore(tmp_path / "profiles.json"), active_profile=None)
    await restore_last_profile(state)
    assert state.active_profile is None
