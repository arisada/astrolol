"""Queue operations, persistence, target resolution and device resolution."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrolol.core.sequencer import (
    ExposureGroup,
    InvalidRequest,
    Lane,
    Sequencer,
    TargetRef,
    TaskNotFound,
    TaskStatus,
)
from plugins.sequencer.devices import resolve_lane_devices
from plugins.sequencer.targets import TargetUnresolvable, resolve_target
from plugins.sequencer.tests.fakes import FakeDeviceManager, Rig, make_task


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_implements_the_core_protocol(rig: Rig) -> None:
    assert isinstance(rig.svc, Sequencer)


async def test_add_assigns_fresh_ids_and_runtime(rig: Rig) -> None:
    task = make_task(
        groups=[ExposureGroup(duration=1, count=2), ExposureGroup(duration=2, count=3)]
    )
    a = await rig.svc.add(task)
    b = await rig.svc.add(task)
    assert a.task.id != task.id and a.task.id != b.task.id
    assert a.task.lanes[0].id != b.task.lanes[0].id
    assert a.runtime.status == TaskStatus.PENDING
    assert [g.frames_done for g in a.runtime.lanes[0].groups] == [0, 0]
    assert len(rig.of("sequencer.queue_changed")) == 2


async def test_insert_positions(rig: Rig) -> None:
    a = await rig.svc.add(make_task("A"))
    b = await rig.svc.add(make_task("B"))
    c = await rig.svc.add(make_task("C"), position=0)
    n = await rig.svc.insert_next(make_task("N"))  # idle: before the first runnable task
    order = [e.task.id for e in await rig.svc.list_tasks()]
    assert order == [n.task.id, c.task.id, a.task.id, b.task.id]


async def test_reorder_and_duplicate(rig: Rig) -> None:
    a = await rig.svc.add(make_task("A"))
    b = await rig.svc.add(make_task("B"))
    c = await rig.svc.add(make_task("C"))
    await rig.svc.reorder([c.task.id, a.task.id])
    assert [e.task.id for e in await rig.svc.list_tasks()] == [c.task.id, a.task.id, b.task.id]
    d = await rig.svc.duplicate(c.task.id)
    names = [e.task.target.name for e in await rig.svc.list_tasks()]
    assert names == ["C", "C", "A", "B"]
    assert d.task.id != c.task.id


async def test_update_keeps_matching_progress(rig: Rig) -> None:
    groups = [
        ExposureGroup(filter_name="L", duration=60, count=10),
        ExposureGroup(filter_name="R", duration=60, count=5),
    ]
    entry = await rig.svc.add(make_task(groups=groups))
    live = rig.svc.find(entry.task.id)
    assert live is not None
    live.runtime.lanes[0].groups[0].frames_done = 4
    live.runtime.lanes[0].groups[1].frames_done = 2

    edited = entry.task.model_copy(deep=True)
    edited.lanes[0].groups[0].count = 20  # count change: progress kept
    edited.lanes[0].groups[1].duration = 120  # different frames: progress reset
    edited.lanes[0].groups.append(ExposureGroup(filter_name="G", duration=60, count=5))
    updated = await rig.svc.update(entry.task.id, edited)
    assert [g.frames_done for g in updated.runtime.lanes[0].groups] == [4, 0, 0]
    assert updated.task.lanes[0].id == entry.task.lanes[0].id


async def test_update_reopens_a_completed_task(rig: Rig) -> None:
    entry = await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=2)]))
    live = rig.svc.find(entry.task.id)
    assert live is not None
    live.runtime.lanes[0].groups[0].frames_done = 2
    live.runtime.status = TaskStatus.COMPLETED
    edited = entry.task.model_copy(deep=True)
    edited.lanes[0].groups[0].count = 4
    updated = await rig.svc.update(entry.task.id, edited)
    assert updated.runtime.status == TaskStatus.INTERRUPTED


async def test_set_status_skip_and_retry(rig: Rig) -> None:
    entry = await rig.svc.add(make_task())
    skipped = await rig.svc.set_status(entry.task.id, "skipped", actor="user")
    assert skipped.runtime.status == TaskStatus.SKIPPED
    assert skipped.runtime.interruptions[-1].kind == "skip"
    retried = await rig.svc.set_status(entry.task.id, "pending")
    assert retried.runtime.status == TaskStatus.PENDING


async def test_reset_progress_and_clear(rig: Rig) -> None:
    a = await rig.svc.add(make_task("A"))
    b = await rig.svc.add(make_task("B"))
    live = rig.svc.find(a.task.id)
    assert live is not None
    live.runtime.lanes[0].groups[0].frames_done = 1
    live.runtime.status = TaskStatus.COMPLETED
    reset = await rig.svc.reset_progress(a.task.id)
    assert reset.runtime.frames_done() == 0
    assert reset.runtime.status == TaskStatus.PENDING

    await rig.svc.set_status(b.task.id, "skipped")
    await rig.svc.clear(["skipped", "completed"])
    assert [e.task.id for e in await rig.svc.list_tasks()] == [a.task.id]


async def test_unknown_task(rig: Rig) -> None:
    with pytest.raises(TaskNotFound):
        await rig.svc.get("nope")
    with pytest.raises(TaskNotFound):
        await rig.svc.remove("nope")


async def test_switch_to_completed_task_is_invalid(rig: Rig) -> None:
    entry = await rig.svc.add(make_task())
    live = rig.svc.find(entry.task.id)
    assert live is not None
    live.runtime.status = TaskStatus.COMPLETED
    with pytest.raises(InvalidRequest):
        await rig.svc.switch_to(entry.task.id)


# ── Persistence ───────────────────────────────────────────────────────────────


async def test_queue_survives_restart(rig: Rig) -> None:
    entry = await rig.svc.add(make_task(groups=[ExposureGroup(duration=1, count=5)]))
    live = rig.svc.find(entry.task.id)
    assert live is not None
    live.runtime.lanes[0].groups[0].frames_done = 3
    live.runtime.status = TaskStatus.RUNNING  # as if the process died mid-task
    await rig.svc.commit()

    restarted = rig.reload()
    got = await restarted.get(entry.task.id)
    assert got.runtime.status == TaskStatus.INTERRUPTED
    assert got.runtime.frames_done() == 3
    assert got.task == entry.task


def test_legacy_state_file_is_deleted(tmp_path: Path) -> None:
    legacy = tmp_path / "sequencer_state.json"
    legacy.write_text(json.dumps({"schema_version": 1, "tasks": {}}))
    Rig(tmp_path)
    assert not legacy.exists()


def test_corrupt_queue_file_starts_empty(tmp_path: Path) -> None:
    (tmp_path / "sequencer_queue.json").write_text("{not json")
    rig = Rig(tmp_path)
    assert rig.svc.entries == []


# ── TargetRef ─────────────────────────────────────────────────────────────────


def test_target_ref_validation() -> None:
    with pytest.raises(ValueError):
        TargetRef(kind="favorite", name="x")
    with pytest.raises(ValueError):
        TargetRef(kind="catalog", name="x")
    with pytest.raises(ValueError):
        TargetRef(kind="coordinates", name="x", ra=10.0)
    TargetRef(kind="current", name="whatever")


def _app(**state: object) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(**state))


async def test_resolve_favorite() -> None:
    fav = SimpleNamespace(ra=10.0, dec=20.0)
    favorites = SimpleNamespace(get=lambda fid: fav if fid == "f1" else None)
    ref = TargetRef(kind="favorite", name="Fav", favorite_id="f1", ra=1.0, dec=2.0)
    got = await resolve_target(ref, _app(target_favorites=favorites))
    assert (got.ra, got.dec, got.source, got.warning) == (10.0, 20.0, "favorite", None)

    gone = TargetRef(kind="favorite", name="Fav", favorite_id="deleted", ra=1.0, dec=2.0)
    got = await resolve_target(gone, _app(target_favorites=favorites))
    assert (got.ra, got.source) == (1.0, "snapshot")
    assert got.warning and "no longer exists" in got.warning


async def test_resolve_catalog() -> None:
    class Resolver:
        async def lookup(self, name: str, when: object = None) -> object:
            return SimpleNamespace(ra=150.0, dec=-10.0) if name == "Jupiter" else None

    ref = TargetRef(kind="catalog", name="Jupiter", catalog_id="Jupiter", ra=1.0, dec=2.0)
    got = await resolve_target(ref, _app(object_resolver=Resolver()))
    assert (got.ra, got.dec, got.source) == (150.0, -10.0, "catalog")

    unknown = TargetRef(kind="catalog", name="Foo", catalog_id="Foo")
    with pytest.raises(TargetUnresolvable):
        await resolve_target(unknown, _app(object_resolver=Resolver()))

    got = await resolve_target(ref, _app())  # resolver plugin disabled → snapshot
    assert got.source == "snapshot"


async def test_unresolvable_target_fails_the_task(rig: Rig) -> None:
    task = make_task(on_error="skip")
    task.target = TargetRef(kind="catalog", name="Nowhere", catalog_id="Nowhere")
    entry = await rig.svc.add(task)
    rig.app.state.object_resolver = SimpleNamespace(lookup=_none_lookup)
    await rig.svc.start()
    await rig.svc.wait_idle()
    rt = (await rig.svc.get(entry.task.id)).runtime
    assert rt.status == TaskStatus.FAILED
    assert "Nowhere" in (rt.last_error or "")


async def _none_lookup(name: str, when: object = None) -> None:
    return None


# ── Devices without a profile tree ────────────────────────────────────────────


def test_device_fallback_only_when_unambiguous() -> None:
    lane = Lane(groups=[ExposureGroup(duration=1, count=1)])
    dm = FakeDeviceManager(
        [("cam1", "camera"), ("fw1", "filter_wheel"), ("m1", "mount"), ("m2", "mount")]
    )
    devices = resolve_lane_devices(_app(device_manager=dm, active_profile=None), lane)
    assert devices.camera_id == "cam1"
    assert devices.filter_wheel_id == "fw1"
    assert devices.mount_id is None  # two mounts: no guess
    assert devices.from_profile is False

    missing = Lane(camera_id="other", groups=[ExposureGroup(duration=1, count=1)])
    assert (
        resolve_lane_devices(_app(device_manager=dm, active_profile=None), missing).camera_id
        is None
    )
