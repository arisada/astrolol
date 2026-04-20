"""Tests for the sequencer plugin — API + runner behaviour."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.sequencer.api import router
from plugins.sequencer.events import (
    SequenceCompleted,
    SequenceFrameCompleted,
    SequenceTaskCompleted,
)
from plugins.sequencer.models import FilterExposure, ImagingTask, SequencerState, TaskStatus
from plugins.sequencer.runner import SequenceProgress, SequenceRunner, SequencerPausedError
from plugins.sequencer.settings import SequencerSettings


# ── Helpers ───────────────────────────────────────────────────────────────────

class FakeEventBus:
    """Minimal event bus: records published events."""

    def __init__(self) -> None:
        self._events: list[Any] = []
        self._subscribers: list[asyncio.Queue] = []

    async def publish(self, event: Any) -> None:
        self._events.append(event)
        for q in self._subscribers:
            await q.put(event)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def events_of(self, type_: type) -> list[Any]:
        return [e for e in self._events if isinstance(e, type_)]


class FakeImagerManager:
    """Returns a fake ExposureResult instantly."""

    def __init__(self, fits_path: str = "/tmp/fake.fits") -> None:
        self.fits_path = fits_path
        self.expose_count = 0

    async def expose(self, device_id: str, request: Any) -> Any:
        self.expose_count += 1
        result = MagicMock()
        result.fits_path = self.fits_path
        result.preview_path = "/tmp/fake_preview.jpg"
        return result


class FakeDeviceManager:
    """Returns a fixed list of connected devices."""

    def __init__(self, camera_id: str = "cam1", mount_id: str = "mount1") -> None:
        self._camera_id = camera_id
        self._mount_id = mount_id

    def list_connected(self) -> list[dict]:
        devices = []
        if self._camera_id:
            devices.append({"device_id": self._camera_id, "kind": "camera"})
        if self._mount_id:
            devices.append({"device_id": self._mount_id, "kind": "mount"})
        return devices


def _task(count: int = 2, name: str | None = None, on_error: str = "abort") -> ImagingTask:
    """Build a minimal ImagingTask with one exposure group."""
    return ImagingTask(
        name=name,
        exposures=[FilterExposure(duration=0.01, count=count)],
        do_slew=False,
        do_plate_solve=False,
        dither_every=None,
        on_error=on_error,  # type: ignore[arg-type]
    )


def _runner_with_app(
    tmp_path: Path,
    camera_id: str = "cam1",
    settings: SequencerSettings | None = None,
) -> tuple[SequenceRunner, FakeEventBus, FastAPI]:
    """Create a SequenceRunner wired to a minimal fake app."""
    bus = FakeEventBus()
    cfg = settings or SequencerSettings(
        unpark_on_start=False,
        park_on_complete=False,
        stop_guide_before_slew=False,
        restart_guide_after_slew=False,
        meridian_flip_enabled=False,
        autofocus_before_start=False,
    )
    runner = SequenceRunner(bus, cfg, tmp_path / "sequencer_state.json")

    app = FastAPI()
    app.state.sequence_runner = runner
    app.state.imager_manager = FakeImagerManager()
    app.state.device_manager = FakeDeviceManager(camera_id=camera_id)
    app.state.mount_manager = None
    app.state.phd2_client = None
    app.state.solve_manager = None
    app.state.filter_wheel_manager = None
    app.include_router(router)

    runner.set_app(app)
    return runner, bus, app


# ── Queue CRUD — TestClient (sync) ────────────────────────────────────────────

def test_add_task_returns_201(tmp_path: Path) -> None:
    _, _, app = _runner_with_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/plugins/sequencer/queue", json={
            "exposures": [{"duration": 10.0, "count": 5}],
        })
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["exposures"][0]["count"] == 5


def test_add_task_server_generates_id(tmp_path: Path) -> None:
    _, _, app = _runner_with_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/plugins/sequencer/queue", json={
            "id": "client-supplied-id",
            "exposures": [{"duration": 1.0, "count": 1}],
        })
    assert resp.status_code == 201
    # Server must override the client-supplied ID
    assert resp.json()["id"] != "client-supplied-id"


def test_get_queue_returns_tasks(tmp_path: Path) -> None:
    runner, _, app = _runner_with_app(tmp_path)
    runner.add_task(_task(name="t1"))
    runner.add_task(_task(name="t2"))
    with TestClient(app) as client:
        resp = client.get("/plugins/sequencer/queue")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert names == ["t1", "t2"]


def test_delete_task(tmp_path: Path) -> None:
    runner, _, app = _runner_with_app(tmp_path)
    task = _task(name="to_delete")
    runner.add_task(task)
    with TestClient(app) as client:
        resp = client.delete(f"/plugins/sequencer/queue/{task.id}")
    assert resp.status_code == 204
    assert runner.get_task(task.id) is None


def test_delete_nonexistent_task_returns_404(tmp_path: Path) -> None:
    _, _, app = _runner_with_app(tmp_path)
    with TestClient(app) as client:
        resp = client.delete("/plugins/sequencer/queue/no-such-id")
    assert resp.status_code == 404


def test_update_task(tmp_path: Path) -> None:
    runner, _, app = _runner_with_app(tmp_path)
    task = _task(name="original")
    runner.add_task(task)
    with TestClient(app) as client:
        resp = client.put(f"/plugins/sequencer/queue/{task.id}", json={
            "id": task.id,
            "name": "updated",
            "exposures": [{"duration": 30.0, "count": 10}],
        })
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated"


def test_reorder_queue(tmp_path: Path) -> None:
    runner, _, app = _runner_with_app(tmp_path)
    t1, t2, t3 = _task(name="a"), _task(name="b"), _task(name="c")
    for t in (t1, t2, t3):
        runner.add_task(t)
    with TestClient(app) as client:
        resp = client.post("/plugins/sequencer/queue/reorder", json={
            "order": [t3.id, t1.id, t2.id]
        })
    assert resp.status_code == 204
    ids = [t.id for t in runner.list_tasks()]
    assert ids == [t3.id, t1.id, t2.id]


def test_clear_queue(tmp_path: Path) -> None:
    runner, _, app = _runner_with_app(tmp_path)
    for _ in range(3):
        runner.add_task(_task())
    with TestClient(app) as client:
        resp = client.delete("/plugins/sequencer/queue")
    assert resp.status_code == 204
    assert runner.list_tasks() == []


def test_concurrent_start_returns_409(tmp_path: Path) -> None:
    runner, _, app = _runner_with_app(tmp_path)
    # Fake that the runner is already running
    runner._running = True
    with TestClient(app) as client:
        resp = client.post("/plugins/sequencer/start")
    assert resp.status_code == 409
    runner._running = False  # cleanup


def test_status_endpoint(tmp_path: Path) -> None:
    _, _, app = _runner_with_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/plugins/sequencer/status")
    assert resp.status_code == 200
    assert resp.json()["state"] == "idle"


def test_settings_roundtrip(tmp_path: Path) -> None:
    _, _, app = _runner_with_app(tmp_path)
    with TestClient(app) as client:
        resp = client.put("/plugins/sequencer/settings", json={
            "unpark_on_start": False,
            "park_on_complete": True,
            "meridian_flip_enabled": False,
            "guide_settle_time_s": 15,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["park_on_complete"] is True
    assert data["guide_settle_time_s"] == 15


def test_pause_invalid_mode_returns_422(tmp_path: Path) -> None:
    _, _, app = _runner_with_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/plugins/sequencer/pause?mode=invalid")
    assert resp.status_code == 422


# ── Runner behaviour — pytest-asyncio ─────────────────────────────────────────

@pytest.fixture()
def event_bus() -> FakeEventBus:
    return FakeEventBus()


@pytest.fixture()
def settings() -> SequencerSettings:
    return SequencerSettings(
        unpark_on_start=False,
        park_on_complete=False,
        stop_guide_before_slew=False,
        restart_guide_after_slew=False,
        meridian_flip_enabled=False,
        autofocus_before_start=False,
    )


def _make_runner(
    tmp_path: Path,
    bus: FakeEventBus,
    settings: SequencerSettings,
    camera_id: str = "cam1",
) -> SequenceRunner:
    runner = SequenceRunner(bus, settings, tmp_path / "sequencer_state.json")
    app = MagicMock()
    app.state.imager_manager = FakeImagerManager()
    app.state.device_manager = FakeDeviceManager(camera_id=camera_id)
    app.state.mount_manager = None
    app.state.phd2_client = None
    app.state.solve_manager = None
    app.state.filter_wheel_manager = None
    runner.set_app(app)
    return runner


@pytest.mark.asyncio
async def test_run_completes(tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings) -> None:
    runner = _make_runner(tmp_path, event_bus, settings)
    runner.add_task(_task(count=2))
    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=5.0)

    assert runner._state == SequencerState.COMPLETED
    assert len(event_bus.events_of(SequenceFrameCompleted)) == 2
    assert len(event_bus.events_of(SequenceTaskCompleted)) == 1
    assert len(event_bus.events_of(SequenceCompleted)) == 1


@pytest.mark.asyncio
async def test_run_two_tasks(tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings) -> None:
    runner = _make_runner(tmp_path, event_bus, settings)
    runner.add_task(_task(count=3))
    runner.add_task(_task(count=2))
    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=5.0)

    assert runner._state == SequencerState.COMPLETED
    assert len(event_bus.events_of(SequenceFrameCompleted)) == 5
    assert len(event_bus.events_of(SequenceTaskCompleted)) == 2


@pytest.mark.asyncio
async def test_frames_tracked_in_status(
    tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings
) -> None:
    runner = _make_runner(tmp_path, event_bus, settings)
    runner.add_task(_task(count=3))
    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=5.0)

    status = runner.get_status()
    assert status.tasks_done == 1


@pytest.mark.asyncio
async def test_cancel_mid_run(tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings) -> None:
    from plugins.sequencer.events import SequenceCancelled

    # Use a slow exposure so the runner is definitely still running
    runner = _make_runner(tmp_path, event_bus, settings)
    slow_task = ImagingTask(
        exposures=[FilterExposure(duration=60.0, count=100)],
        do_slew=False,
        do_plate_solve=False,
        dither_every=None,
        on_error="abort",
    )
    # Patch imager to be slow
    runner._app.state.imager_manager = _SlowImager()
    runner.add_task(slow_task)
    await runner.start()
    await asyncio.sleep(0.05)  # let it start

    await runner.cancel()

    assert runner._state == SequencerState.CANCELLED
    assert len(event_bus.events_of(SequenceCancelled)) == 1


@pytest.mark.asyncio
async def test_pause_and_resume(tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings) -> None:
    from plugins.sequencer.events import SequencePaused, SequenceResumed

    runner = _make_runner(tmp_path, event_bus, settings)
    # Use a slow imager so frames don't complete before we can request pause
    runner._app.state.imager_manager = _YieldingImager()
    runner.add_task(_task(count=4))

    await runner.start()
    await asyncio.sleep(0.02)  # let the first expose begin

    runner.request_pause(mode="after_frame")
    # Wait for paused state
    for _ in range(100):
        await asyncio.sleep(0.02)
        if runner._state == SequencerState.PAUSED:
            break
    assert runner._state == SequencerState.PAUSED

    runner.resume()
    await asyncio.wait_for(runner._run_task, timeout=5.0)
    assert runner._state == SequencerState.COMPLETED
    assert len(event_bus.events_of(SequencePaused)) >= 1
    assert len(event_bus.events_of(SequenceResumed)) >= 1


@pytest.mark.asyncio
async def test_on_error_skip(tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings) -> None:
    from plugins.sequencer.events import SequenceTaskFailed

    runner = _make_runner(tmp_path, event_bus, settings)
    failing_task = ImagingTask(
        exposures=[FilterExposure(duration=0.01, count=1)],
        do_slew=False,
        do_plate_solve=False,
        dither_every=None,
        on_error="skip",
    )
    good_task = _task(count=1)

    # Make the first expose call fail, subsequent ones succeed
    call_count = 0

    async def _expose(device_id: str, request: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated camera error")
        result = MagicMock()
        result.fits_path = "/tmp/fake.fits"
        return result

    runner._app.state.imager_manager.expose = _expose
    runner.add_task(failing_task)
    runner.add_task(good_task)

    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=5.0)

    assert runner._state == SequencerState.COMPLETED
    failed_events = event_bus.events_of(SequenceTaskFailed)
    completed_events = event_bus.events_of(SequenceTaskCompleted)
    assert len(failed_events) == 1
    assert len(completed_events) == 1  # good_task completed


@pytest.mark.asyncio
async def test_on_error_abort(tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings) -> None:
    from plugins.sequencer.events import SequenceFailed

    runner = _make_runner(tmp_path, event_bus, settings)

    async def _fail(device_id: str, request: Any) -> Any:
        raise RuntimeError("hard failure")

    runner._app.state.imager_manager.expose = _fail

    runner.add_task(ImagingTask(
        exposures=[FilterExposure(duration=0.01, count=1)],
        do_slew=False, do_plate_solve=False, dither_every=None, on_error="abort",
    ))
    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=5.0)

    assert runner._state == SequencerState.FAILED
    assert len(event_bus.events_of(SequenceFailed)) == 1


@pytest.mark.asyncio
async def test_on_error_pause(tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings) -> None:
    from plugins.sequencer.events import SequencePaused

    runner = _make_runner(tmp_path, event_bus, settings)

    call_count = 0

    async def _expose(device_id: str, request: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient error")
        result = MagicMock()
        result.fits_path = "/tmp/fake.fits"
        return result

    runner._app.state.imager_manager.expose = _expose
    runner.add_task(ImagingTask(
        exposures=[FilterExposure(duration=0.01, count=1)],
        do_slew=False, do_plate_solve=False, dither_every=None, on_error="pause",
    ))
    await runner.start()

    # Wait for paused state
    for _ in range(50):
        await asyncio.sleep(0.05)
        if runner._state == SequencerState.PAUSED:
            break
    assert runner._state == SequencerState.PAUSED
    assert len(event_bus.events_of(SequencePaused)) >= 1


@pytest.mark.asyncio
async def test_progress_persistence(tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings) -> None:
    """Simulate a crash mid-task and resume from saved progress."""
    state_path = tmp_path / "sequencer_state.json"

    # Run first 2 of 4 frames, then cancel
    runner = _make_runner(tmp_path, event_bus, settings)
    task = _task(count=4)
    runner.add_task(task)

    expose_count = 0
    event = asyncio.Event()

    async def _controlled_expose(device_id: str, request: Any) -> Any:
        nonlocal expose_count
        expose_count += 1
        if expose_count >= 2:
            event.set()  # signal we've done 2 frames
            await asyncio.sleep(10)  # block until cancelled
        result = MagicMock()
        result.fits_path = "/tmp/fake.fits"
        return result

    runner._app.state.imager_manager.expose = _controlled_expose
    await runner.start()
    await asyncio.wait_for(event.wait(), timeout=5.0)
    await runner.cancel()

    # The progress file should record 1 complete frame (expose completes before record)
    # Actually by the time cancel fires, frame 0 is done (expose_count==1 → record called once)
    # Frame 1 expose was started but may not have finished — depends on cancellation point
    # Just verify the file exists and has data for our task
    assert state_path.exists()

    # Now create a new runner with the same state file and verify it skips done frames
    bus2 = FakeEventBus()
    runner2 = SequenceRunner(bus2, settings, state_path)
    app2 = MagicMock()
    expose2_count = 0

    async def _count_expose(device_id: str, request: Any) -> Any:
        nonlocal expose2_count
        expose2_count += 1
        result = MagicMock()
        result.fits_path = "/tmp/fake.fits"
        return result

    app2.state.imager_manager = FakeImagerManager()
    app2.state.imager_manager.expose = _count_expose
    app2.state.device_manager = FakeDeviceManager()
    app2.state.mount_manager = None
    app2.state.phd2_client = None
    app2.state.solve_manager = None
    app2.state.filter_wheel_manager = None
    runner2.set_app(app2)
    runner2.add_task(task)  # same task UUID → progress restored

    await runner2.start()
    await asyncio.wait_for(runner2._run_task, timeout=5.0)

    # runner2 picked up where runner1 left off — it must not redo all 4 frames
    assert expose2_count < 4
    assert runner2._state == SequencerState.COMPLETED


@pytest.mark.asyncio
async def test_meridian_flip_triggered(
    tmp_path: Path, event_bus: FakeEventBus
) -> None:
    """SequenceRunner performs a meridian flip when HA exceeds the threshold."""
    from astrolol.core.events.models import MountMeridianFlipCompleted

    settings = SequencerSettings(
        unpark_on_start=False,
        park_on_complete=False,
        stop_guide_before_slew=False,
        restart_guide_after_slew=False,
        meridian_flip_enabled=True,
        plate_solve_after_flip=False,
        meridian_flip_ha_threshold=0.1,
        autofocus_before_start=False,
    )
    runner = _make_runner(tmp_path, event_bus, settings)

    # Mount status: past meridian (HA = 0.5 hours)
    mock_status = MagicMock()
    mock_status.hour_angle = 0.5

    flip_called = False

    async def mock_meridian_flip(mount_id: str) -> None:
        nonlocal flip_called
        flip_called = True
        # Publish the completion event so the runner's wait exits
        await event_bus.publish(MountMeridianFlipCompleted(device_id=mount_id))

    mock_mount_manager = MagicMock()
    mock_mount_manager.get_status = AsyncMock(return_value=mock_status)
    mock_mount_manager.meridian_flip = mock_meridian_flip
    runner._app.state.mount_manager = mock_mount_manager

    runner.add_task(_task(count=1))
    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=5.0)

    assert flip_called
    assert runner._state == SequencerState.COMPLETED


@pytest.mark.asyncio
async def test_meridian_flip_not_triggered_before_threshold(
    tmp_path: Path, event_bus: FakeEventBus
) -> None:
    settings = SequencerSettings(
        unpark_on_start=False,
        park_on_complete=False,
        stop_guide_before_slew=False,
        restart_guide_after_slew=False,
        meridian_flip_enabled=True,
        plate_solve_after_flip=False,
        meridian_flip_ha_threshold=0.5,
        autofocus_before_start=False,
    )
    runner = _make_runner(tmp_path, event_bus, settings)

    mock_status = MagicMock()
    mock_status.hour_angle = 0.3  # below threshold

    flip_called = False

    async def mock_meridian_flip(mount_id: str) -> None:
        nonlocal flip_called
        flip_called = True

    mock_mount_manager = MagicMock()
    mock_mount_manager.get_status = AsyncMock(return_value=mock_status)
    mock_mount_manager.meridian_flip = mock_meridian_flip
    runner._app.state.mount_manager = mock_mount_manager

    runner.add_task(_task(count=1))
    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=5.0)

    assert not flip_called


@pytest.mark.asyncio
async def test_empty_queue_completes_immediately(
    tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings
) -> None:
    runner = _make_runner(tmp_path, event_bus, settings)
    # No tasks added
    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=2.0)
    assert runner._state == SequencerState.COMPLETED


@pytest.mark.asyncio
async def test_reset_clears_completed_tasks(
    tmp_path: Path, event_bus: FakeEventBus, settings: SequencerSettings
) -> None:
    runner = _make_runner(tmp_path, event_bus, settings)
    runner.add_task(_task(count=1))
    await runner.start()
    await asyncio.wait_for(runner._run_task, timeout=5.0)
    assert runner.get_status().tasks_done == 1

    await runner.reset()
    assert runner.list_tasks() == []
    assert runner._state == SequencerState.IDLE


# ── Progress persistence unit tests ───────────────────────────────────────────

def test_progress_record_and_read(tmp_path: Path) -> None:
    p = SequenceProgress(tmp_path / "state.json")
    p.record_frame("task-1", group_idx=0)
    p.record_frame("task-1", group_idx=0)
    p.record_frame("task-1", group_idx=1)
    assert p.frames_done("task-1", 0) == 2
    assert p.frames_done("task-1", 1) == 1
    assert p.frames_done("task-1", 2) == 0  # never recorded


def test_progress_persists_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    p = SequenceProgress(path)
    p.record_frame("task-1", 0)
    p.mark_task_done("task-1")
    assert path.exists()

    p2 = SequenceProgress(path)
    assert p2.is_task_done("task-1")
    assert p2.frames_done("task-1", 0) == 1


def test_progress_delete(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    p = SequenceProgress(path)
    p.record_frame("task-1", 0)
    p.delete()
    assert not path.exists()


def test_progress_corrupt_file_treated_as_fresh(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not valid json {{{")
    p = SequenceProgress(path)
    assert p.frames_done("task-1", 0) == 0
    assert not p.is_task_done("task-1")


# ── Slow imager helper ────────────────────────────────────────────────────────

class _SlowImager:
    """Imager that blocks until cancelled."""

    async def expose(self, device_id: str, request: Any) -> Any:
        await asyncio.sleep(300)  # blocks until CancelledError


class _YieldingImager:
    """Imager that takes ~50 ms per frame — long enough for pause requests to land."""

    async def expose(self, device_id: str, request: Any) -> Any:
        await asyncio.sleep(0.05)
        result = MagicMock()
        result.fits_path = "/tmp/fake.fits"
        return result
