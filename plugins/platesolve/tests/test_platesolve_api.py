"""Tests for the plate-solving plugin API."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.config.user_settings import UserSettings
from plugins.platesolve.api import router
from plugins.platesolve.models import SolveJob, SolveRequest, SolveResult
from plugins.platesolve.plugin import get_plugin
from plugins.platesolve.settings import PlatesolveSettings
from plugins.platesolve.solver import SolveManager


class FakeProfileStore:
    def __init__(self) -> None:
        self._settings = UserSettings()

    def get_user_settings(self) -> UserSettings:
        return self._settings

    def update_user_settings(self, settings: UserSettings) -> UserSettings:
        self._settings = settings
        return settings


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
    app.state.profile_store = FakeProfileStore()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def fake(client: TestClient) -> FakeSolveManager:
    return client.app.state.solve_manager  # type: ignore[attr-defined]


# ── POST /platesolve/solve ────────────────────────────────────────────────────

def test_start_solve_returns_201(client: TestClient) -> None:
    r = client.post("/plugins/platesolve/solve", json={"fits_path": "/tmp/image.fits"})
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
    r = client.post("/plugins/platesolve/solve", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["request"]["ra_hint"] == 83.82
    assert data["request"]["dec_hint"] == -5.39


# ── GET /platesolve/jobs ──────────────────────────────────────────────────────

def test_list_jobs_empty(client: TestClient) -> None:
    r = client.get("/plugins/platesolve/jobs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_jobs_multiple(client: TestClient) -> None:
    client.post("/plugins/platesolve/solve", json={"fits_path": "/tmp/a.fits"})
    client.post("/plugins/platesolve/solve", json={"fits_path": "/tmp/b.fits"})
    r = client.get("/plugins/platesolve/jobs")
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 2
    # Most recent first
    assert jobs[0]["request"]["fits_path"] == "/tmp/b.fits"
    assert jobs[1]["request"]["fits_path"] == "/tmp/a.fits"


# ── GET /platesolve/{id}/status ───────────────────────────────────────────────

def test_get_status_pending(client: TestClient, fake: FakeSolveManager) -> None:
    r = client.post("/plugins/platesolve/solve", json={"fits_path": "/tmp/img.fits"})
    job_id = r.json()["id"]

    r2 = client.get(f"/plugins/platesolve/{job_id}/status")
    assert r2.status_code == 200
    assert r2.json()["status"] == "pending"


def test_get_status_completed(client: TestClient, fake: FakeSolveManager) -> None:
    completed = _make_job(status="completed", result=_DUMMY_RESULT)
    fake._jobs[completed.id] = completed

    r = client.get(f"/plugins/platesolve/{completed.id}/status")
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

    r = client.get(f"/plugins/platesolve/{failed.id}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "failed"
    assert data["error"] == "No stars found"
    assert data["result"] is None


def test_get_status_not_found(client: TestClient) -> None:
    r = client.get("/plugins/platesolve/nonexistent/status")
    assert r.status_code == 404


# ── DELETE /platesolve/{id}/cancel ────────────────────────────────────────────

def test_cancel_running_job(client: TestClient, fake: FakeSolveManager) -> None:
    r = client.post("/plugins/platesolve/solve", json={"fits_path": "/tmp/img.fits"})
    job_id = r.json()["id"]

    r2 = client.delete(f"/plugins/platesolve/{job_id}/cancel")
    assert r2.status_code == 204
    assert fake._jobs[job_id].status == "cancelled"


def test_cancel_already_completed_is_noop(client: TestClient, fake: FakeSolveManager) -> None:
    completed = _make_job(status="completed", result=_DUMMY_RESULT)
    fake._jobs[completed.id] = completed

    r = client.delete(f"/plugins/platesolve/{completed.id}/cancel")
    # Still 204 — idempotent, not an error
    assert r.status_code == 204
    assert fake._jobs[completed.id].status == "completed"  # unchanged


def test_cancel_already_cancelled_is_noop(client: TestClient, fake: FakeSolveManager) -> None:
    cancelled = _make_job(status="cancelled")
    fake._jobs[cancelled.id] = cancelled

    r = client.delete(f"/plugins/platesolve/{cancelled.id}/cancel")
    assert r.status_code == 204


def test_cancel_not_found(client: TestClient) -> None:
    r = client.delete("/plugins/platesolve/nonexistent/cancel")
    assert r.status_code == 404


# ── Plugin manifest ───────────────────────────────────────────────────────────

def test_plugin_manifest() -> None:
    plugin = get_plugin()
    assert plugin.manifest.id == "platesolve"
    assert plugin.manifest.name == "Plate Solving"
    assert plugin.manifest.version == "0.1.0"


# ── GET /platesolve/db_status ─────────────────────────────────────────────────

def test_db_status_not_installed(client: TestClient) -> None:
    r = client.get("/plugins/platesolve/db_status")
    assert r.status_code == 200
    data = r.json()
    assert data["installed"] is False
    assert data["db_path"] == "/nonexistent/astap"


def test_db_status_installed(client: TestClient, fake: FakeSolveManager, tmp_path) -> None:
    # Plant a fake .290 file
    (tmp_path / "d05_0000.290").touch()
    fake._astap_db_path = str(tmp_path)

    r = client.get("/plugins/platesolve/db_status")
    assert r.status_code == 200
    assert r.json()["installed"] is True


# ── POST /platesolve/install_db ───────────────────────────────────────────────

def test_install_db_returns_202(client: TestClient) -> None:
    async def _noop(event_bus) -> None:  # type: ignore[type-arg]
        pass

    with patch("plugins.platesolve.api._do_install_db", _noop):
        r = client.post("/plugins/platesolve/install_db")
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


# ── Real astap_cli integration test ───────────────────────────────────────────

import bz2
import shutil
from pathlib import Path

_TEST_FITS_BZ2 = Path(__file__).parent / "test.fits.bz2"
_ASTAP_BIN = "astap_cli"


def _find_db() -> str | None:
    for p in ["/opt/astap", "/usr/share/astap"]:
        path = Path(p)
        if path.is_dir() and any(path.iterdir()):
            return p
    return None


_needs_astap = pytest.mark.skipif(
    shutil.which(_ASTAP_BIN) is None,
    reason="astap_cli not installed",
)
_needs_db = pytest.mark.skipif(
    _find_db() is None,
    reason="astap star database not found in /opt/astap or /usr/share/astap",
)


@pytest.mark.asyncio
@_needs_astap
@_needs_db
async def test_solve_real_image(tmp_path) -> None:
    """End-to-end solve of the bundled test.fits using the real astap_cli."""
    fits_copy = tmp_path / "test.fits"
    fits_copy.write_bytes(bz2.decompress(_TEST_FITS_BZ2.read_bytes()))

    db_path = _find_db()
    manager = SolveManager(
        event_bus=FakeEventBus(),
        astap_bin=_ASTAP_BIN,
        astap_db_path=db_path,
    )
    req = SolveRequest(
        fits_path=str(fits_copy),
        ra_hint=35.18,
        dec_hint=57.005,
        radius=30.0,
        tolerance=0.007,
    )
    job = await manager.submit(req)

    # Poll until terminal state (up to 120 s)
    updated = None
    for _ in range(240):
        await asyncio.sleep(0.5)
        updated = manager.get(job.id)
        if updated and updated.status in ("completed", "failed", "cancelled"):
            break

    assert updated is not None
    assert updated.status == "completed", f"Solve failed: {updated.error}"
    assert abs(updated.result.ra - 35.18) < 0.5, f"RA mismatch: {updated.result.ra}"
    assert abs(updated.result.dec - 57.005) < 0.5, f"Dec mismatch: {updated.result.dec}"

    # Allow the event loop to drain subprocess transports before it closes,
    # preventing PytestUnraisableExceptionWarning from BaseSubprocessTransport.__del__.
    await asyncio.sleep(0.1)


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



# ── GET/PUT /plugins/platesolve/settings ─────────────────────────────────────

def test_get_settings_returns_defaults(client: TestClient) -> None:
    r = client.get("/plugins/platesolve/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["exposure_duration"] == 5.0
    assert data["binning"] == 1
    assert data["after_solve"] == "nothing"
    assert data["camera_id"] == ""


def test_put_settings_persists(client: TestClient) -> None:
    payload = {
        "astap_bin": "astap_cli",
        "astap_db_path": "/opt/astap",
        "astap_search_radius": 15.0,
        "astap_tolerance": 0.005,
        "pixel_size_um": 3.76,
        "exposure_duration": 10.0,
        "binning": 2,
        "after_solve": "sync",
        "camera_id": "cam_asi294",
    }
    r = client.put("/plugins/platesolve/settings", json=payload)
    assert r.status_code == 200
    assert r.json()["exposure_duration"] == 10.0
    assert r.json()["camera_id"] == "cam_asi294"

    # Verify persistence via GET
    r2 = client.get("/plugins/platesolve/settings")
    assert r2.json()["camera_id"] == "cam_asi294"
    assert r2.json()["binning"] == 2


# ── _compute_fov (equipment-tree resolution) ──────────────────────────────────

async def _fov_rig(tmp_path, focal_length_mm: float = 600.0):
    """A connected camera sitting on an OTA in the equipment tree, plus a fake request
    object exposing the app.state _compute_fov reads from."""
    from types import SimpleNamespace

    from astrolol.config.user_settings import UserSettings
    from astrolol.core.events import EventBus
    from astrolol.devices.config import DeviceConfig
    from astrolol.devices.manager import DeviceManager
    from astrolol.devices.registry import DeviceRegistry
    from astrolol.equipment.models import CameraItem, OTAItem
    from astrolol.equipment.store import EquipmentStore
    from astrolol.profiles.models import Profile, ProfileNode
    from tests.conftest import FakeCamera

    registry = DeviceRegistry()
    registry.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    device_manager = DeviceManager(registry=registry, event_bus=EventBus())
    await device_manager.connect(DeviceConfig(device_id="cam1", kind="camera", adapter_key="fake_camera"))

    inv_store = EquipmentStore(tmp_path / "inventory.json")
    ota = inv_store.create(OTAItem(name="Main OTA", focal_length=focal_length_mm, aperture=100.0))
    cam_item = inv_store.create(CameraItem(name="Cam", adapter_key="fake_camera", connect_params={}))
    profile = Profile(name="rig", roots=[
        ProfileNode(item_id=ota.id, children=[ProfileNode(item_id=cam_item.id)]),
    ])

    profile_store = FakeProfileStore()
    profile_store._settings = UserSettings(plugin_settings={"platesolve": {"pixel_size_um": 3.76}})

    app = SimpleNamespace(state=SimpleNamespace(
        active_profile=profile,
        equipment_store=inv_store,
        device_manager=device_manager,
        profile_store=profile_store,
    ))
    return SimpleNamespace(app=app), inv_store, ota


@pytest.mark.asyncio
async def test_compute_fov_resolves_focal_length_from_the_equipment_tree(tmp_path) -> None:
    """Regression: FOV computation used to read the (now-removed) profile.telescope.
    focal_length flat field — must resolve the connected camera's ancestor OTA from the
    equipment tree instead, since a profile can have more than one optical path."""
    from plugins.platesolve.api import _compute_fov
    from tests.conftest import make_fake_fits

    request, _inv_store, _ota = await _fov_rig(tmp_path, focal_length_mm=600.0)
    fits_path = make_fake_fits(tmp_path / "test.fits", width=64, height=64)

    fov = await _compute_fov(str(fits_path), request)

    assert fov is not None
    assert fov > 0


@pytest.mark.asyncio
async def test_compute_fov_scales_inversely_with_focal_length(tmp_path) -> None:
    from plugins.platesolve.api import _compute_fov
    from tests.conftest import make_fake_fits

    fits_path = make_fake_fits(tmp_path / "test.fits", width=64, height=64)

    short_request, _inv_store, _ota = await _fov_rig(tmp_path / "short", focal_length_mm=300.0)
    long_request, _inv_store2, _ota2 = await _fov_rig(tmp_path / "long", focal_length_mm=1200.0)

    short_fov = await _compute_fov(str(fits_path), short_request)
    long_fov = await _compute_fov(str(fits_path), long_request)

    assert short_fov is not None and long_fov is not None
    assert long_fov < short_fov


@pytest.mark.asyncio
async def test_compute_fov_none_without_an_active_profile(tmp_path) -> None:
    from types import SimpleNamespace

    from plugins.platesolve.api import _compute_fov
    from tests.conftest import make_fake_fits

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        active_profile=None, equipment_store=None, device_manager=None, profile_store=FakeProfileStore(),
    )))
    fits_path = make_fake_fits(tmp_path / "test.fits")

    assert await _compute_fov(str(fits_path), request) is None


@pytest.mark.asyncio
async def test_compute_fov_none_when_camera_has_no_ota(tmp_path) -> None:
    """A camera not sitting under any OTA in the tree has nothing to compute FOV from."""
    from types import SimpleNamespace

    from astrolol.core.events import EventBus
    from astrolol.devices.config import DeviceConfig
    from astrolol.devices.manager import DeviceManager
    from astrolol.devices.registry import DeviceRegistry
    from astrolol.equipment.models import CameraItem
    from astrolol.equipment.store import EquipmentStore
    from astrolol.profiles.models import Profile, ProfileNode
    from plugins.platesolve.api import _compute_fov
    from tests.conftest import FakeCamera, make_fake_fits

    registry = DeviceRegistry()
    registry.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    device_manager = DeviceManager(registry=registry, event_bus=EventBus())
    await device_manager.connect(DeviceConfig(device_id="cam1", kind="camera", adapter_key="fake_camera"))

    inv_store = EquipmentStore(tmp_path / "inventory.json")
    cam_item = inv_store.create(CameraItem(name="Cam", adapter_key="fake_camera", connect_params={}))
    profile = Profile(name="rig", roots=[ProfileNode(item_id=cam_item.id)])

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        active_profile=profile, equipment_store=inv_store, device_manager=device_manager,
        profile_store=FakeProfileStore(),
    )))
    fits_path = make_fake_fits(tmp_path / "test.fits")

    assert await _compute_fov(str(fits_path), request) is None
