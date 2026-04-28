"""Tests for EquipmentStore and the /inventory API endpoints."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from astrolol.equipment.models import (
    CameraItem,
    FocuserItem,
    MountItem,
    OTAItem,
    ProfileNode,
    SiteItem,
    VALID_CHILD_TYPES,
)
from astrolol.equipment.store import EquipmentStore
from astrolol.main import create_app


# ===========================================================================
# EquipmentStore unit tests (no HTTP)
# ===========================================================================


@pytest.fixture
def store(tmp_path):
    return EquipmentStore(tmp_path / "inventory.json")


def _camera(name: str = "ZWO ASI294") -> CameraItem:
    return CameraItem(name=name)


def _mount(name: str = "EQ6-R") -> MountItem:
    return MountItem(name=name)


def test_empty_store(store):
    assert store.list() == []


def test_create_and_get_item(store):
    item = store.create(_camera())
    assert item.name == "ZWO ASI294"
    assert item.id  # UUID auto-assigned
    assert store.get(item.id).id == item.id


def test_list_items(store):
    store.create(_camera("cam1"))
    store.create(_mount("mount1"))
    assert len(store.list()) == 2


def test_get_missing_raises(store):
    with pytest.raises(KeyError):
        store.get("does-not-exist")


def test_update_item(store):
    item = store.create(_camera("old name"))
    updated = CameraItem(id=item.id, name="new name")
    result = store.update(updated)
    assert result.name == "new name"
    assert store.get(item.id).name == "new name"


def test_update_missing_raises(store):
    with pytest.raises(KeyError):
        store.update(_camera())


def test_delete_item(store):
    item = store.create(_camera())
    store.delete(item.id)
    assert store.list() == []


def test_delete_missing_raises(store):
    with pytest.raises(KeyError):
        store.delete("does-not-exist")


def test_persistence(tmp_path):
    path = tmp_path / "inventory.json"
    s1 = EquipmentStore(path)
    item = s1.create(_mount("Persisted mount"))
    s2 = EquipmentStore(path)
    assert s2.get(item.id).name == "Persisted mount"


def test_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text("not json {{{")
    store = EquipmentStore(path)
    assert store.list() == []


def test_wrong_schema_version_starts_fresh(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"schema_version": 999, "items": []}))
    store = EquipmentStore(path)
    assert store.list() == []


def test_all_item_types_roundtrip(tmp_path):
    path = tmp_path / "inventory.json"
    s = EquipmentStore(path)
    items = [
        SiteItem(name="Backyard", latitude=48.8, longitude=2.3, altitude=50.0),
        MountItem(name="EQ6-R", indi_driver="indi_eqmod_telescope"),
        OTAItem(name="ED80", focal_length=600.0, aperture=80.0),
        CameraItem(name="ASI294MC", pixel_size_um=4.63),
        FocuserItem(name="Pegasus FocusCube"),
    ]
    for item in items:
        s.create(item)

    s2 = EquipmentStore(path)
    assert len(s2.list()) == len(items)
    types = {i.type for i in s2.list()}  # type: ignore[union-attr]
    assert types == {"site", "mount", "ota", "camera", "focuser"}


# ===========================================================================
# ProfileNode model tests
# ===========================================================================


def test_profile_node_defaults():
    node = ProfileNode(item_id="abc")
    assert node.role is None
    assert node.children == []


def test_profile_node_nested():
    leaf = ProfileNode(item_id="cam-id")
    ota = ProfileNode(item_id="ota-id", children=[leaf])
    mount = ProfileNode(item_id="mount-id", children=[ota])
    assert mount.children[0].children[0].item_id == "cam-id"


def test_valid_child_types_completeness():
    """Every item type that can be a parent must declare its valid children."""
    all_types = {"site", "mount", "ota", "camera", "filter_wheel", "focuser", "rotator", "gps"}
    assert set(VALID_CHILD_TYPES.keys()) == all_types


# ===========================================================================
# /inventory HTTP endpoint tests
# ===========================================================================


@pytest.fixture
def client(tmp_path):
    app = create_app()
    # Inject a fresh store backed by a temp file so tests are isolated
    app.state.equipment_store = EquipmentStore(tmp_path / "inventory.json")
    return TestClient(app)


def test_list_empty(client):
    r = client.get("/inventory")
    assert r.status_code == 200
    assert r.json() == []


def test_create_camera(client):
    payload = {"type": "camera", "name": "ASI2600MC", "pixel_size_um": 3.76}
    r = client.post("/inventory", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "ASI2600MC"
    assert data["type"] == "camera"
    assert "id" in data


def test_get_item(client):
    r = client.post("/inventory", json={"type": "mount", "name": "EQ6-R"})
    item_id = r.json()["id"]
    r2 = client.get(f"/inventory/{item_id}")
    assert r2.status_code == 200
    assert r2.json()["name"] == "EQ6-R"


def test_get_missing_item(client):
    r = client.get("/inventory/does-not-exist")
    assert r.status_code == 404


def test_update_item_endpoint(client):
    r = client.post("/inventory", json={"type": "focuser", "name": "Old name"})
    item = r.json()
    item["name"] = "New name"
    r2 = client.put(f"/inventory/{item['id']}", json=item)
    assert r2.status_code == 200
    assert r2.json()["name"] == "New name"


def test_update_id_mismatch(client):
    r = client.post("/inventory", json={"type": "focuser", "name": "Focuser"})
    item = r.json()
    item["id"] = "different-id"
    r2 = client.put("/inventory/original-id", json=item)
    assert r2.status_code == 400


def test_update_missing_item(client):
    payload = {"type": "mount", "id": "no-such-id", "name": "Ghost"}
    r = client.put("/inventory/no-such-id", json=payload)
    assert r.status_code == 404


def test_delete_item_endpoint(client):
    r = client.post("/inventory", json={"type": "ota", "name": "ED80", "focal_length": 600, "aperture": 80})
    item_id = r.json()["id"]
    r2 = client.delete(f"/inventory/{item_id}")
    assert r2.status_code == 204
    r3 = client.get(f"/inventory/{item_id}")
    assert r3.status_code == 404


def test_delete_missing_item(client):
    r = client.delete("/inventory/no-such-id")
    assert r.status_code == 404


def test_list_after_creates(client):
    client.post("/inventory", json={"type": "camera", "name": "Cam1", "pixel_size_um": 3.76})
    client.post("/inventory", json={"type": "mount", "name": "Mount1"})
    r = client.get("/inventory")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_site_item_roundtrip(client):
    payload = {
        "type": "site",
        "name": "Backyard",
        "latitude": 48.8,
        "longitude": 2.3,
        "altitude": 50.0,
        "timezone": "Europe/Paris",
    }
    r = client.post("/inventory", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["latitude"] == 48.8
    assert data["timezone"] == "Europe/Paris"


def test_filter_wheel_with_filters(client):
    payload = {
        "type": "filter_wheel",
        "name": "EFW 8",
        "filter_names": ["L", "R", "G", "B", "Ha", "OIII", "SII", "UV/IR"],
    }
    r = client.post("/inventory", json=payload)
    assert r.status_code == 201
    assert r.json()["filter_names"] == ["L", "R", "G", "B", "Ha", "OIII", "SII", "UV/IR"]
