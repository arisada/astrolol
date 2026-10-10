"""API-layer tests for the polar-scope reticle route: request plumbing (site lookup)
around reticle.py's pure math, which test_reticle.py already covers independently."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.config.user_settings import UserSettings
from astrolol.equipment.models import MountItem, SiteItem
from astrolol.equipment.store import EquipmentStore
from astrolol.profiles.models import Profile, ProfileNode
from astrolol.plugins.polar_align.api import router


class FakeProfileStore:
    def __init__(self) -> None:
        self._settings = UserSettings()

    def get_user_settings(self) -> UserSettings:
        return self._settings

    def update_user_settings(self, settings: UserSettings) -> UserSettings:
        self._settings = settings
        return settings


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
    app.include_router(router)
    app.state._test_mount = mount  # for tests that need the mount node id
    return TestClient(app)


def test_get_reticle_returns_angle(client: TestClient) -> None:
    r = client.get("/plugins/polar_align/reticle")
    assert r.status_code == 200
    data = r.json()
    assert 0.0 <= data["angle_deg"] < 360.0


def test_get_reticle_rejects_southern_hemisphere(tmp_path) -> None:
    app = FastAPI()
    profile, store, _mount = _site_fixtures(tmp_path, latitude=-33.0, longitude=151.0)
    app.state.active_profile = profile
    app.state.equipment_store = store
    app.state.profile_store = FakeProfileStore()
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
    app.include_router(router)
    client = TestClient(app)

    r = client.get("/plugins/polar_align/reticle")
    assert r.status_code == 404
