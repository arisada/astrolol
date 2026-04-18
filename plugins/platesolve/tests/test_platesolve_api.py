"""Tests for the plate-solving plugin API."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.platesolve.api import router
from plugins.platesolve.models import SolveJob, SolveRequest, SolveResult
from plugins.platesolve.plugin import get_plugin
from plugins.platesolve.solver import SolveManager


# ── Fake manager ──────────────────────────────────────────────────────────────

_DUMMY_RESULT = SolveResult(
    ra=83.8221,
    dec=-5.3911,
    rotation=0.54,
    pixel_scale=1.09,
    field_w=0.93,
    field_h=0.62,
    duration_ms=3200,
)

_NOW = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_ID_COUNTER = 0


def _make_job(status="pending", result=None, error=None) -> SolveJob:
    global _ID_COUNTER
    _ID_COUNTER += 1
    return SolveJob(
        id=f"job-{_ID_COUNTER:04d}",
        status=status,
        request=SolveRequest(fits_path="/tmp/test.fits"),
        result=result,
        error=error,
        created_at=_NOW,
        completed_at=_NOW if status in ("completed", "failed", "cancelled") else None,
    )


class FakeSolveManager:
    def __init__(self) -> None:
        self._jobs: dict[str, SolveJob] = {}
        self._astap_db_path = "/nonexistent/astap"  # no DB files → installed=False

    async def submit(self, request: SolveRequest) -> SolveJob:
        global _ID_COUNTER
        _ID_COUNTER += 1
        job = SolveJob(
            id=f"job-{_ID_COUNTER:04d}",
            status="pending",
            request=request,
            created_at=_NOW,
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> SolveJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[SolveJob]:
        return list(reversed(list(self._jobs.values())))

    async def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in ("completed", "failed", "cancelled"):
            return False
        self._jobs[job_id] = job.model_copy(update={"status": "cancelled"})
        return True


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_counter():
    global _ID_COUNTER
    _ID_COUNTER = 0


class FakeEventBus:
    async def publish(self, event) -> None:
        pass


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.state.solve_manager = FakeSolveManager()
    app.state.event_bus = FakeEventBus()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def fake(client: TestClient) -> FakeSolveManager:
    return client.app.state.solve_manager  # type: ignore[attr-defined]


# ── POST /platesolve/solve ────────────────────────────────────────────────────

def test_start_solve_returns_201(client: TestClient) -> None:
    r = client.post("/platesolve/solve", json={"fits_path": "/tmp/image.fits"})
    assert r.status_code == 201
    data = r.json()
    assert data["id"] == "job-0001"
    assert data["status"] == "pending"
    assert data["request"]["fits_path"] == "/tmp/image.fits"
    assert data["result"] is None


def test_start_solve_with_hints(client: TestClient) -> None:
    body = {
        "fits_path": "/tmp/img.fits",
        "ra_hint": 83.82,
        "dec_hint": -5.39,
        "radius": 15.0,
        "fov": 1.0,
    }
    r = client.post("/platesolve/solve", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["request"]["ra_hint"] == 83.82
    assert data["request"]["dec_hint"] == -5.39


# ── GET /platesolve/jobs ──────────────────────────────────────────────────────

def test_list_jobs_empty(client: TestClient) -> None:
    r = client.get("/platesolve/jobs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_jobs_multiple(client: TestClient) -> None:
    client.post("/platesolve/solve", json={"fits_path": "/tmp/a.fits"})
    client.post("/platesolve/solve", json={"fits_path": "/tmp/b.fits"})
    r = client.get("/platesolve/jobs")
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 2
    # Most recent first
    assert jobs[0]["request"]["fits_path"] == "/tmp/b.fits"
    assert jobs[1]["request"]["fits_path"] == "/tmp/a.fits"


# ── GET /platesolve/{id}/status ───────────────────────────────────────────────

def test_get_status_pending(client: TestClient, fake: FakeSolveManager) -> None:
    r = client.post("/platesolve/solve", json={"fits_path": "/tmp/img.fits"})
    job_id = r.json()["id"]

    r2 = client.get(f"/platesolve/{job_id}/status")
    assert r2.status_code == 200
    assert r2.json()["status"] == "pending"


def test_get_status_completed(client: TestClient, fake: FakeSolveManager) -> None:
    completed = _make_job(status="completed", result=_DUMMY_RESULT)
    fake._jobs[completed.id] = completed

    r = client.get(f"/platesolve/{completed.id}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["result"]["ra"] == pytest.approx(83.8221)
    assert data["result"]["dec"] == pytest.approx(-5.3911)
    assert data["result"]["pixel_scale"] == pytest.approx(1.09)
    assert data["result"]["duration_ms"] == 3200


def test_get_status_failed(client: TestClient, fake: FakeSolveManager) -> None:
    failed = _make_job(status="failed", error="No stars found")
    fake._jobs[failed.id] = failed

    r = client.get(f"/platesolve/{failed.id}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "failed"
    assert data["error"] == "No stars found"
    assert data["result"] is None


def test_get_status_not_found(client: TestClient) -> None:
    r = client.get("/platesolve/nonexistent/status")
    assert r.status_code == 404


# ── DELETE /platesolve/{id}/cancel ────────────────────────────────────────────

def test_cancel_running_job(client: TestClient, fake: FakeSolveManager) -> None:
    r = client.post("/platesolve/solve", json={"fits_path": "/tmp/img.fits"})
    job_id = r.json()["id"]

    r2 = client.delete(f"/platesolve/{job_id}/cancel")
    assert r2.status_code == 204
    assert fake._jobs[job_id].status == "cancelled"


def test_cancel_already_completed_is_noop(client: TestClient, fake: FakeSolveManager) -> None:
    completed = _make_job(status="completed", result=_DUMMY_RESULT)
    fake._jobs[completed.id] = completed

    r = client.delete(f"/platesolve/{completed.id}/cancel")
    # Still 204 — idempotent, not an error
    assert r.status_code == 204
    assert fake._jobs[completed.id].status == "completed"  # unchanged


def test_cancel_already_cancelled_is_noop(client: TestClient, fake: FakeSolveManager) -> None:
    cancelled = _make_job(status="cancelled")
    fake._jobs[cancelled.id] = cancelled

    r = client.delete(f"/platesolve/{cancelled.id}/cancel")
    assert r.status_code == 204


def test_cancel_not_found(client: TestClient) -> None:
    r = client.delete("/platesolve/nonexistent/cancel")
    assert r.status_code == 404


# ── Plugin manifest ───────────────────────────────────────────────────────────

def test_plugin_manifest() -> None:
    plugin = get_plugin()
    assert plugin.manifest.id == "platesolve"
    assert plugin.manifest.name == "Plate Solving"
    assert plugin.manifest.version == "0.1.0"


# ── GET /platesolve/db_status ─────────────────────────────────────────────────

def test_db_status_not_installed(client: TestClient) -> None:
    r = client.get("/platesolve/db_status")
    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is False
    assert data["db_path"] == "/nonexistent/astap"


def test_db_status_installed(client: TestClient, fake: FakeSolveManager, tmp_path) -> None:
    # Plant a fake .290 file
    (tmp_path / "d05_0000.290").touch()
    fake._astap_db_path = str(tmp_path)

    r = client.get("/platesolve/db_status")
    assert r.status_code == 200
    assert r.json()["installed"] is True


# ── POST /platesolve/install_db ───────────────────────────────────────────────

def test_install_db_returns_202(client: TestClient) -> None:
    r = client.post("/platesolve/install_db")
    assert r.status_code == 202
    assert r.json()["status"] == "started"


# ── SolveManager unit tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manager_submit_creates_task() -> None:
    manager = SolveManager(event_bus=FakeEventBus(), astap_bin="astap_cli")

    # Patch _solve so it doesn't actually run astap_cli
    async def fake_solve(req, job_id):
        await asyncio.sleep(0)
        return _DUMMY_RESULT.model_copy(update={"duration_ms": 0})

    manager._solve = fake_solve  # type: ignore[method-assign]

    req = SolveRequest(fits_path="/tmp/test.fits")
    job = await manager.submit(req)
    assert job.status == "pending"
    assert job.id in manager._jobs

    # Let the task run
    await asyncio.sleep(0.05)
    updated = manager.get(job.id)
    assert updated is not None
    assert updated.status == "completed"


@pytest.mark.asyncio
async def test_manager_cancel_stops_task() -> None:
    manager = SolveManager(event_bus=FakeEventBus(), astap_bin="astap_cli")

    async def slow_solve(req, job_id):
        await asyncio.sleep(60)
        return _DUMMY_RESULT

    manager._solve = slow_solve  # type: ignore[method-assign]

    req = SolveRequest(fits_path="/tmp/test.fits")
    job = await manager.submit(req)
    await asyncio.sleep(0.01)  # let it start

    result = await manager.cancel(job.id)
    assert result is True

    # Give the task a moment to handle cancellation
    await asyncio.sleep(0.05)
    updated = manager.get(job.id)
    assert updated is not None
    assert updated.status == "cancelled"


@pytest.mark.asyncio
async def test_manager_cancel_not_found_raises() -> None:
    manager = SolveManager(event_bus=FakeEventBus(), astap_bin="astap_cli")
    with pytest.raises(KeyError):
        await manager.cancel("nonexistent")


@pytest.mark.asyncio
async def test_manager_failed_job_on_bad_binary() -> None:
    manager = SolveManager(
        event_bus=FakeEventBus(),
        astap_bin="__nonexistent_binary__",
        astap_db_path="/tmp",
    )

    import os, tempfile
    with tempfile.NamedTemporaryFile(suffix=".fits", delete=False) as f:
        tmp = f.name
    try:
        req = SolveRequest(fits_path=tmp)
        job = await manager.submit(req)
        await asyncio.sleep(0.1)
        updated = manager.get(job.id)
        assert updated is not None
        assert updated.status == "failed"
        assert "not found" in (updated.error or "").lower()
    finally:
        os.unlink(tmp)
