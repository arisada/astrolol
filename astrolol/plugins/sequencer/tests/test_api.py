"""REST layer: routing, status codes, error mapping."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.plugins.sequencer.api import router
from astrolol.plugins.sequencer.tests.fakes import Rig


def _task_body(
    name: str = "M 42", filter_name: str | None = None, count: int = 2
) -> dict[str, Any]:
    return {
        "target": {"kind": "coordinates", "name": name, "ra": 83.8, "dec": -5.4},
        "lanes": [{"groups": [{"filter_name": filter_name, "duration": 1, "count": count}]}],
    }


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


@pytest.fixture
def client(rig: Rig) -> TestClient:
    app = FastAPI()
    for name, value in vars(rig.app.state).items():
        setattr(app.state, name, value)
    app.state.sequencer = rig.svc
    rig.svc.app = app
    rig.svc.runner.app = app
    app.include_router(router)
    return TestClient(app)


def test_queue_crud(client: TestClient) -> None:
    r = client.post("/plugins/sequencer/queue", json=_task_body("A"))
    assert r.status_code == 201
    a = r.json()
    assert a["runtime"]["status"] == "pending"
    tid = a["task"]["id"]

    b = client.post("/plugins/sequencer/queue", json=_task_body("B")).json()
    assert [e["task"]["target"]["name"] for e in client.get("/plugins/sequencer/queue").json()] == [
        "A",
        "B",
    ]

    edited = a["task"] | {"name": "Renamed"}
    r = client.put(f"/plugins/sequencer/queue/{tid}", json=edited)
    assert r.status_code == 200
    assert r.json()["task"]["name"] == "Renamed"

    r = client.post("/plugins/sequencer/queue/reorder", json={"order": [b["task"]["id"]]})
    assert r.status_code == 204
    assert client.get("/plugins/sequencer/queue").json()[0]["task"]["id"] == b["task"]["id"]

    r = client.post(f"/plugins/sequencer/queue/{tid}/duplicate")
    assert r.status_code == 201
    r = client.post(f"/plugins/sequencer/queue/{tid}/skip")
    assert r.json()["runtime"]["status"] == "skipped"
    r = client.post(f"/plugins/sequencer/queue/{tid}/unskip")
    assert r.json()["runtime"]["status"] == "pending"

    assert client.delete(f"/plugins/sequencer/queue/{tid}").status_code == 204
    assert client.get(f"/plugins/sequencer/queue/{tid}").status_code == 404


def test_invalid_task_is_422(client: TestClient) -> None:
    body = _task_body()
    body["lanes"] = []
    assert client.post("/plugins/sequencer/queue", json=body).status_code == 422
    body = _task_body()
    body["target"] = {"kind": "favorite", "name": "x"}
    assert client.post("/plugins/sequencer/queue", json=body).status_code == 422


def test_start_with_empty_queue_reports_preflight(client: TestClient) -> None:
    r = client.post("/plugins/sequencer/start")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["report"]["issues"][0]["code"] == "nothing_to_run"


def test_preflight_route(client: TestClient) -> None:
    client.post("/plugins/sequencer/queue", json=_task_body(filter_name="OIII"))
    report = client.post("/plugins/sequencer/preflight").json()
    assert report["ok"] is False
    assert report["issues"][0]["code"] == "filter_not_in_wheel"


def test_control_when_idle(client: TestClient) -> None:
    assert client.post("/plugins/sequencer/pause").status_code == 409
    assert client.post("/plugins/sequencer/stop").status_code == 204  # idempotent
    assert client.get("/plugins/sequencer/status").json()["run_state"] == "idle"


def test_full_run_over_rest(client: TestClient) -> None:
    with client:  # keep the event loop alive between requests
        client.post("/plugins/sequencer/queue", json=_task_body(count=2))
        assert client.post("/plugins/sequencer/start", json={"actor": "user"}).status_code == 202
        assert client.post("/plugins/sequencer/start").status_code == 409
        deadline = time.monotonic() + 5
        while client.get("/plugins/sequencer/status").json()["run_state"] != "idle":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        status = client.get("/plugins/sequencer/status").json()
        assert status["last_run_outcome"] == "completed"
        entry = client.get("/plugins/sequencer/queue").json()[0]
        assert entry["runtime"]["status"] == "completed"


def test_settings_roundtrip(client: TestClient) -> None:
    s = client.get("/plugins/sequencer/settings").json()
    s["dither_pixels"] = 7.5
    assert client.put("/plugins/sequencer/settings", json=s).status_code == 200
    assert client.get("/plugins/sequencer/settings").json()["dither_pixels"] == 7.5
