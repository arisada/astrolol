"""Tests for ProfileStore and the /profiles API endpoints."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.api.profiles import _apply_tree_context, _push_live_context, _find_mount_for_camera
from astrolol.equipment.models import CameraItem, MountItem, OTAItem, SiteItem
from astrolol.equipment.store import EquipmentStore
from astrolol.main import create_app
from astrolol.profiles.models import Profile, ObserverLocation, ProfileNode, Telescope
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
                "params": {"device_name": device_name},
            })()
            self.instance = instance

    class _DM:
        def __init__(self):
            self._devices = {k: v for k, v in entries.items()}

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
