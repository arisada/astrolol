"""GET/PUT /guiding/active: which enabled guiding plugin is in use."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.api.guiding import router
from astrolol.config.user_settings import UserSettings
from astrolol.core.events import EventBus
from astrolol.core.guiding import register_guider


class _Guider:
    def __init__(self, name: str, active: bool = False) -> None:
        self.name, self.is_active = name, active

    def status(self) -> Any:
        return SimpleNamespace(active=self.is_active)


class _Store:
    def __init__(self) -> None:
        self.settings = UserSettings()

    def get_user_settings(self) -> UserSettings:
        return self.settings

    def update_user_settings(self, settings: UserSettings) -> None:
        self.settings = settings


@pytest.fixture
def rig() -> SimpleNamespace:
    app = FastAPI()
    app.state.event_bus = EventBus()
    app.state.profile_store = _Store()
    app.state.imager_manager = None
    mine, phd2 = _Guider("builtin"), _Guider("phd2")
    register_guider(app, mine, "guider")  # type: ignore[arg-type]
    register_guider(app, phd2, "phd2")  # type: ignore[arg-type]
    app.include_router(router)
    return SimpleNamespace(app=app, client=TestClient(app), mine=mine, phd2=phd2)


def test_lists_the_enabled_guiders_and_the_active_one(rig: SimpleNamespace) -> None:
    assert rig.client.get("/guiding/active").json() == {"active": "guider", "available": ["guider", "phd2"]}


def test_choosing_a_guider_saves_the_choice_and_announces_it(rig: SimpleNamespace) -> None:
    queue = rig.app.state.event_bus.subscribe()

    r = rig.client.put("/guiding/active", json={"guider": "phd2"})

    assert r.status_code == 200 and r.json()["active"] == "phd2"
    assert rig.app.state.guider is rig.phd2
    assert rig.app.state.profile_store.settings.active_guider == "phd2"
    event = queue.get_nowait()
    assert (event.type, event.active) == ("guiding.active_changed", "phd2")


def test_the_choice_is_refused_while_the_current_guider_guides(rig: SimpleNamespace) -> None:
    rig.mine.is_active = True

    r = rig.client.put("/guiding/active", json={"guider": "phd2"})

    assert r.status_code == 409 and "stop it" in r.json()["detail"]
    assert rig.app.state.guider is rig.mine
    assert rig.app.state.profile_store.settings.active_guider is None


def test_an_unknown_guider_is_a_404(rig: SimpleNamespace) -> None:
    assert rig.client.put("/guiding/active", json={"guider": "nope"}).status_code == 404
