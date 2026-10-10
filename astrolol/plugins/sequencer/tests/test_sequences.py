"""Named sequences (server library) and file import/export."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.sequencer import ExposureGroup, TaskStatus
from astrolol.plugins.sequencer.api import router
from astrolol.plugins.sequencer.sequences import SequenceLibrary, slug
from astrolol.plugins.sequencer.tests.fakes import Rig, make_task


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


@pytest.fixture
def client(rig: Rig, tmp_path: Path) -> TestClient:
    app = FastAPI()
    for name, value in vars(rig.app.state).items():
        setattr(app.state, name, value)
    app.state.sequencer = rig.svc
    app.state.sequencer_library = SequenceLibrary(tmp_path / "sequences")
    rig.svc.app = app
    rig.svc.runner.app = app
    app.include_router(router)
    return TestClient(app)


async def _two_tasks(rig: Rig) -> list[str]:
    a = await rig.svc.add(
        make_task("M 31", groups=[ExposureGroup(filter_name="L", duration=300, count=20)])
    )
    b = await rig.svc.add(make_task("M 42", groups=[ExposureGroup(duration=60, count=10)]))
    return [a.task.id, b.task.id]


def test_slug() -> None:
    assert slug("  M 31 — LRGB!  ") == "m-31-lrgb"
    assert slug("***") == "sequence"


async def test_save_list_load_delete(rig: Rig, client: TestClient) -> None:
    ids = await _two_tasks(rig)
    live = rig.svc.find(ids[0])
    assert live is not None
    live.runtime.lanes[0].groups[0].frames_done = 7  # progress must not be saved

    r = client.post(
        "/plugins/sequencer/sequences",
        json={"name": "Autumn galaxies", "description": "two targets"},
    )
    assert r.status_code == 201
    assert r.json()["tasks"] == 2 and r.json()["targets"] == ["M 31", "M 42"]
    assert r.json()["exposure_s"] == 300 * 20 + 60 * 10

    assert (
        client.post("/plugins/sequencer/sequences", json={"name": "Autumn galaxies"}).status_code
        == 409
    )
    assert (
        client.post(
            "/plugins/sequencer/sequences", json={"name": "Autumn galaxies", "overwrite": True}
        ).status_code
        == 201
    )

    listing = client.get("/plugins/sequencer/sequences").json()
    assert [(s["id"], s["name"]) for s in listing] == [("autumn-galaxies", "Autumn galaxies")]

    loaded = client.post("/plugins/sequencer/sequences/autumn-galaxies/load")
    assert loaded.status_code == 201
    new = loaded.json()
    assert len(new) == 2
    assert {e["task"]["id"] for e in new}.isdisjoint(ids)  # fresh ids
    assert all(e["runtime"]["status"] == "pending" for e in new)
    assert all(g["frames_done"] == 0 for e in new for g in e["runtime"]["lanes"][0]["groups"])
    assert len(rig.svc.entries) == 4  # appended, originals kept

    assert client.delete("/plugins/sequencer/sequences/autumn-galaxies").status_code == 204
    assert client.get("/plugins/sequencer/sequences/autumn-galaxies").status_code == 404


async def test_save_selected_tasks_and_skip_completed(rig: Rig, client: TestClient) -> None:
    ids = await _two_tasks(rig)
    live = rig.svc.find(ids[1])
    assert live is not None
    live.runtime.status = TaskStatus.COMPLETED
    r = client.post(
        "/plugins/sequencer/sequences", json={"name": "only open", "include_completed": False}
    )
    assert r.json()["targets"] == ["M 31"]
    r = client.post("/plugins/sequencer/sequences", json={"name": "just m42", "task_ids": [ids[1]]})
    assert r.json()["targets"] == ["M 42"]
    assert (
        client.post(
            "/plugins/sequencer/sequences", json={"name": "x", "task_ids": ["nope"]}
        ).status_code
        == 404
    )


async def test_download_and_upload_files(rig: Rig, client: TestClient) -> None:
    ids = await _two_tasks(rig)
    one = client.get(f"/plugins/sequencer/export?ids={ids[0]}")
    assert one.status_code == 200
    assert 'filename="m-31.json"' in one.headers["content-disposition"]
    doc = one.json()
    assert doc["format"] == "astrolol-sequence" and doc["version"] == 1
    assert doc["name"] == "M 31" and len(doc["tasks"]) == 1
    assert doc["tasks"][0]["id"] == ""  # definitions only

    everything = client.get("/plugins/sequencer/export").json()
    assert len(everything["tasks"]) == 2

    r = client.post("/plugins/sequencer/import", json=everything)
    assert r.status_code == 201 and len(r.json()) == 2
    assert len(rig.svc.entries) == 4

    # a downloaded file can go into the library, and back
    assert client.put("/plugins/sequencer/sequences", json=doc).status_code == 201
    assert client.get("/plugins/sequencer/sequences").json()[0]["name"] == "M 31"


def test_invalid_files_are_rejected(client: TestClient) -> None:
    assert (
        client.post("/plugins/sequencer/import", json={"format": "other", "tasks": []}).status_code
        == 422
    )
    assert (
        client.post(
            "/plugins/sequencer/import",
            json={"format": "astrolol-sequence", "version": 1, "name": "x", "tasks": []},
        ).status_code
        == 422
    )
    assert client.get("/plugins/sequencer/export").status_code == 422  # empty queue


def test_unreadable_files_are_skipped(tmp_path: Path) -> None:
    lib = SequenceLibrary(tmp_path)
    (tmp_path / "broken.json").write_text("{nope")
    assert lib.list() == []


async def test_names_with_slashes(client: TestClient, rig: Rig) -> None:
    await rig.svc.add(make_task("NGC 7000"))
    r = client.post("/plugins/sequencer/sequences", json={"name": "Summer 2026 / narrowband"})
    assert r.json()["id"] == "summer-2026-narrowband"
    doc = client.get("/plugins/sequencer/sequences/summer-2026-narrowband").json()
    assert doc["name"] == "Summer 2026 / narrowband"
