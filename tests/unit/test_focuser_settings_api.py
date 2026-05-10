"""API tests for focuser device settings endpoints."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.api.focuser import router
from astrolol.config.user_settings import UserSettings


class FakeProfileStore:
    def __init__(self) -> None:
        self._settings = UserSettings()

    def get_user_settings(self) -> UserSettings:
        return self._settings

    def update_user_settings(self, settings: UserSettings) -> UserSettings:
        self._settings = settings
        return settings


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.state.profile_store = FakeProfileStore()
    app.include_router(router)
    return TestClient(app)


# ── GET /{device_id}/settings ─────────────────────────────────────────────────

def test_get_settings_returns_defaults(client: TestClient) -> None:
    r = client.get("/focuser/foc1/settings")
    assert r.status_code == 200
    assert r.json() == {"step": 100}


def test_get_settings_independent_per_device(client: TestClient) -> None:
    client.put("/focuser/foc1/settings", json={"step": 50})
    r = client.get("/focuser/foc2/settings")
    assert r.json()["step"] == 100  # foc2 still at default


# ── PUT /{device_id}/settings ─────────────────────────────────────────────────

def test_put_settings_persists(client: TestClient) -> None:
    r = client.put("/focuser/foc1/settings", json={"step": 250})
    assert r.status_code == 200
    assert r.json()["step"] == 250
    assert client.get("/focuser/foc1/settings").json()["step"] == 250


def test_put_settings_rejects_zero_step(client: TestClient) -> None:
    r = client.put("/focuser/foc1/settings", json={"step": 0})
    assert r.status_code == 422


def test_put_settings_rejects_negative_step(client: TestClient) -> None:
    r = client.put("/focuser/foc1/settings", json={"step": -10})
    assert r.status_code == 422


def test_put_settings_does_not_affect_other_devices(client: TestClient) -> None:
    client.put("/focuser/foc1/settings", json={"step": 500})
    r = client.get("/focuser/foc2/settings")
    assert r.json()["step"] == 100
