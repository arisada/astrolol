"""Routes of the live star view: plumbing around starview.py, which test_starview.py covers."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.plugins.polar_align.api import router
from astrolol.plugins.polar_align.wizard import WizardEngine


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.state.polar_align_engine = WizardEngine(app, None)
    app.include_router(router)
    return TestClient(app)


def test_idle_before_anything_started(client: TestClient) -> None:
    body = client.get("/plugins/polar_align/wizard/star_view").json()
    assert body["state"] == "idle"
    assert client.get("/plugins/polar_align/wizard/star_view/frame.jpg").status_code == 404


def test_cannot_start_without_a_run(client: TestClient) -> None:
    r = client.post("/plugins/polar_align/wizard/star_view", json={})
    assert r.status_code == 404


def test_exposure_is_validated(client: TestClient) -> None:
    assert client.post("/plugins/polar_align/wizard/star_view", json={"exposure_s": 0}).status_code == 422
    assert client.post("/plugins/polar_align/wizard/star_view", json={"exposure_s": 60}).status_code == 422


def test_stop_is_harmless_when_idle(client: TestClient) -> None:
    assert client.delete("/plugins/polar_align/wizard/star_view").status_code == 204
