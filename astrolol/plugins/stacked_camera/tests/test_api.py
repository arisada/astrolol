"""Tests for the stacked camera's settings API."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.config.user_settings import UserSettings
from astrolol.plugins.stacked_camera.api import router


class FakeProfileStore:
    def __init__(self) -> None:
        self._settings = UserSettings()

    def get_user_settings(self) -> UserSettings:
        return self._settings

    def update_user_settings(self, settings: UserSettings) -> None:
        self._settings = settings


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.state.profile_store = FakeProfileStore()
    app.include_router(router)
    return TestClient(app)


def test_defaults(client: TestClient) -> None:
    r = client.get("/plugins/stacked_camera/settings")
    assert r.status_code == 200
    assert r.json() == {"sub_exposure": 2.0}


def test_settings_are_saved(client: TestClient) -> None:
    r = client.put("/plugins/stacked_camera/settings", json={"sub_exposure": 5})
    assert r.status_code == 200
    assert client.get("/plugins/stacked_camera/settings").json() == {"sub_exposure": 5.0}


@pytest.mark.parametrize("value", [0, -1, 61])
def test_a_sub_exposure_out_of_range_is_refused(client: TestClient, value: float) -> None:
    r = client.put("/plugins/stacked_camera/settings", json={"sub_exposure": value})
    assert r.status_code == 422
    assert client.get("/plugins/stacked_camera/settings").json() == {"sub_exposure": 2.0}


def test_other_plugin_settings_are_left_alone(client: TestClient) -> None:
    store = client.app.state.profile_store
    current = store.get_user_settings()
    store.update_user_settings(current.model_copy(update={"plugin_settings": {"other": {"a": 1}}}))
    client.put("/plugins/stacked_camera/settings", json={"sub_exposure": 3})
    assert store.get_user_settings().plugin_settings["other"] == {"a": 1}
