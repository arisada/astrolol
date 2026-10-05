"""Tests for the flat wizard plugin's FastAPI router."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from astrolol.core.plugin_api import PluginContext
from plugins.flat_wizard.models import FlatWizardConfig, FlatWizardRun
from plugins.flat_wizard.plugin import FlatWizardPlugin


def _make_app() -> FastAPI:
    app = FastAPI()
    ctx = PluginContext(
        event_bus=EventBus(),
        device_manager=MagicMock(),
        device_registry=MagicMock(),
        profile_store=MagicMock(),
    )
    FlatWizardPlugin().setup(app, ctx)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


_VALID_BODY = {
    "camera_id": "cam_1",
    "filters": [{"filter_name": None, "count": 10}],
}


def test_get_run_returns_404_when_no_run(client: TestClient) -> None:
    resp = client.get("/plugins/flat_wizard/run")
    assert resp.status_code == 404


def test_abort_returns_204_when_no_run(client: TestClient) -> None:
    resp = client.post("/plugins/flat_wizard/abort")
    assert resp.status_code == 204


def test_start_validates_required_fields(client: TestClient) -> None:
    resp = client.post("/plugins/flat_wizard/start", json={})
    assert resp.status_code == 422


def test_start_validates_at_least_one_filter(client: TestClient) -> None:
    resp = client.post(
        "/plugins/flat_wizard/start", json={"camera_id": "cam_1", "filters": []}
    )
    assert resp.status_code == 422


def test_start_validates_target_pct_range(client: TestClient) -> None:
    resp = client.post(
        "/plugins/flat_wizard/start",
        json={**_VALID_BODY, "target_pct": 150},
    )
    assert resp.status_code == 422


def test_start_returns_409_without_sequencer(client: TestClient) -> None:
    """The sequencer plugin isn't set up in this test app, so the engine has
    nowhere to send the solved flats — start() must refuse clearly, not run anyway."""
    resp = client.post("/plugins/flat_wizard/start", json=_VALID_BODY)
    assert resp.status_code == 409
    assert "sequencer" in resp.json()["detail"].lower()


def test_start_conflict_when_already_running(client: TestClient) -> None:
    app = _make_app()
    app.state.sequencer = AsyncMock()
    engine = app.state.flat_wizard_engine

    fake_task = MagicMock()
    fake_task.done.return_value = False
    engine._task = fake_task
    engine._current_run = FlatWizardRun(
        config=FlatWizardConfig(**_VALID_BODY), status="running", total_filters=1,
    )

    with TestClient(app) as tc:
        resp = tc.post("/plugins/flat_wizard/start", json=_VALID_BODY)
    assert resp.status_code == 409
