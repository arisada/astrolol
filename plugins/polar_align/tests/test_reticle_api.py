"""API-layer tests for the polar-scope reticle routes: request plumbing (site lookup,
calibration persistence, optional mount status read) around reticle.py's pure math,
which test_reticle.py already covers independently."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.config.user_settings import UserSettings
from astrolol.equipment.models import MountItem, SiteItem
from astrolol.equipment.store import EquipmentStore
from astrolol.profiles.models import Profile, ProfileNode
from plugins.polar_align.api import router


class FakeProfileStore:
    def __init__(self) -> None:
        self._settings = UserSettings()

    def get_user_settings(self) -> UserSettings:
        return self._settings

    def update_user_settings(self, settings: UserSettings) -> UserSettings:
        self._settings = settings
        return settings


class FakeMountManager:
    def __init__(self, hour_angle: float | None = 1.5) -> None:
        self.hour_angle = hour_angle
        self.get_status_calls: list[str] = []

    async def get_status(self, mount_id: str) -> Any:
        from types import SimpleNamespace

        self.get_status_calls.append(mount_id)
        return SimpleNamespace(hour_angle=self.hour_angle)


def _site_fixtures(tmp_path, latitude: float = 48.0, longitude: float = 11.0):
    store = EquipmentStore(tmp_path / "inventory.json")
    site = store.create(SiteItem(name="s", latitude=latitude, longitude=longitude, altitude=0.0))
    mount = store.create(MountItem(name="m"))
    profile = Profile(name="p", roots=[ProfileNode(item_id=site.id, children=[ProfileNode(item_id=mount.id)])])
    return profile, store, mount


@pytest.fixture()
def client(tmp_path) -> TestClient:
    app = FastAPI()
    profile, store, mount = _site_fixtures(tmp_path)
    app.state.active_profile = profile
    app.state.equipment_store = store
    app.state.profile_store = FakeProfileStore()
    app.state.mount_manager = FakeMountManager()
    app.include_router(router)
    app.state._test_mount = mount  # for tests that need the mount node id
    return TestClient(app)


def test_get_reticle_uncalibrated_returns_raw_angle(client: TestClient) -> None:
    r = client.get("/plugins/polar_align/reticle")
    assert r.status_code == 200
    data = r.json()
    assert data["calibrated"] is False
    assert data["axis_at_home"] is None
    assert 0.0 <= data["angle_deg"] < 360.0
    assert 30.0 < data["radius_arcmin"] < 45.0


def test_get_reticle_rejects_southern_hemisphere(tmp_path) -> None:
    app = FastAPI()
    profile, store, _mount = _site_fixtures(tmp_path, latitude=-33.0, longitude=151.0)
    app.state.active_profile = profile
    app.state.equipment_store = store
    app.state.profile_store = FakeProfileStore()
    app.state.mount_manager = FakeMountManager()
    app.include_router(router)
    client = TestClient(app)

    r = client.get("/plugins/polar_align/reticle")
    assert r.status_code == 422
    assert "northern" in r.json()["detail"].lower()


def test_get_reticle_without_site_returns_404(tmp_path) -> None:
    app = FastAPI()
    app.state.active_profile = None
    app.state.equipment_store = None
    app.state.profile_store = FakeProfileStore()
    app.state.mount_manager = FakeMountManager()
    app.include_router(router)
    client = TestClient(app)

    r = client.get("/plugins/polar_align/reticle")
    assert r.status_code == 404


def test_calibrate_then_get_shows_near_zero_angle(client: TestClient) -> None:
    mount_node_id = client.app.state._test_mount.id  # type: ignore[attr-defined]
    r = client.post("/plugins/polar_align/reticle/calibrate", json={"mount_node_id": mount_node_id})
    assert r.status_code == 200
    calibration = r.json()
    assert calibration["home_ha_hours"] is None  # no mount_id was given

    r2 = client.get("/plugins/polar_align/reticle", params={"mount_node_id": mount_node_id})
    assert r2.status_code == 200
    data = r2.json()
    assert data["calibrated"] is True
    assert data["angle_deg"] == pytest.approx(0.0, abs=0.5) or data["angle_deg"] == pytest.approx(360.0, abs=0.5)


def test_calibrate_with_mount_id_records_home_ha_and_checks_it_later(client: TestClient) -> None:
    mount_node_id = client.app.state._test_mount.id  # type: ignore[attr-defined]
    mount_manager: FakeMountManager = client.app.state.mount_manager  # type: ignore[attr-defined]
    mount_manager.hour_angle = 2.0

    r = client.post(
        "/plugins/polar_align/reticle/calibrate",
        json={"mount_node_id": mount_node_id, "mount_id": "m1"},
    )
    assert r.status_code == 200
    assert r.json()["home_ha_hours"] == pytest.approx(2.0)
    assert mount_manager.get_status_calls == ["m1"]

    # RA axis hasn't moved -- still at home.
    r2 = client.get(
        "/plugins/polar_align/reticle",
        params={"mount_node_id": mount_node_id, "mount_id": "m1"},
    )
    assert r2.json()["axis_at_home"] is True

    # Now it has.
    mount_manager.hour_angle = 2.5
    r3 = client.get(
        "/plugins/polar_align/reticle",
        params={"mount_node_id": mount_node_id, "mount_id": "m1"},
    )
    assert r3.json()["axis_at_home"] is False


def test_delete_calibration_reverts_to_uncalibrated(client: TestClient) -> None:
    mount_node_id = client.app.state._test_mount.id  # type: ignore[attr-defined]
    client.post("/plugins/polar_align/reticle/calibrate", json={"mount_node_id": mount_node_id})

    r = client.delete(f"/plugins/polar_align/reticle/calibration/{mount_node_id}")
    assert r.status_code == 204

    r2 = client.get("/plugins/polar_align/reticle", params={"mount_node_id": mount_node_id})
    assert r2.json()["calibrated"] is False


def test_delete_calibration_is_a_noop_when_never_calibrated(client: TestClient) -> None:
    r = client.delete("/plugins/polar_align/reticle/calibration/never-calibrated")
    assert r.status_code == 204


def test_calibration_for_one_mount_node_does_not_affect_another(client: TestClient) -> None:
    mount_node_id = client.app.state._test_mount.id  # type: ignore[attr-defined]
    client.post("/plugins/polar_align/reticle/calibrate", json={"mount_node_id": mount_node_id})

    r = client.get("/plugins/polar_align/reticle", params={"mount_node_id": "some-other-mount"})
    assert r.json()["calibrated"] is False
