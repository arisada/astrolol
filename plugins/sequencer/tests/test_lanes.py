"""Parallel lanes: the rig schedule, estimates, and multi-camera runs (phase 4)."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

from astrolol.core.sequencer import ExposureGroup, Lane, RunOutcome, TaskStatus
from plugins.sequencer import lanes as lanes_mod
from plugins.sequencer.lanes import RigSchedule, estimate_lanes
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.tests.fakes import Rig, make_task, wait_until


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# ── RigSchedule ───────────────────────────────────────────────────────────────


def test_schedule_without_dithering_never_blocks() -> None:
    s = RigSchedule(Clock())
    s.set_primary(None, None, [])
    assert s.next_mount_op() == math.inf
    assert s.fits(10_000, 10)


def test_schedule_follows_the_primary_exposure() -> None:
    clock = Clock()
    s = RigSchedule(clock)
    s.set_primary(exposure_end=1100.0, frames_to_dither=1, upcoming=[])  # dither after this frame
    assert s.next_mount_op() == 1100.0
    assert s.fits(80, 10)  # 1000 + 90 ≤ 1100
    assert not s.fits(95, 10)
    s.set_primary(exposure_end=1100.0, frames_to_dither=3, upcoming=[100.0, 100.0, 100.0])
    assert s.next_mount_op() == 1300.0  # this frame + the next two


def test_schedule_when_the_primary_is_between_frames() -> None:
    s = RigSchedule(Clock())
    s.set_primary(None, 2, [60.0, 60.0, 60.0])
    assert s.next_mount_op() == 1120.0
    s.set_primary(None, 0, [60.0])  # a dither is due now
    assert s.next_mount_op() == 1000.0


def test_schedule_flip_busy_and_primary_done() -> None:
    s = RigSchedule(Clock())
    s.set_primary(1600.0, 1, [])
    s.flip_at = 1200.0
    assert s.next_mount_op() == 1200.0
    s.mount_busy = True
    assert s.next_mount_op() == 1000.0
    s.mount_busy = False
    s.primary_done = True
    assert s.next_mount_op() == 1200.0  # no more dithers, the flip still counts
    s.flip_at = None
    assert s.next_mount_op() == math.inf


async def test_wait_secondaries_idle() -> None:
    s = RigSchedule()
    s.set_busy("b", True)

    async def release() -> None:
        await asyncio.sleep(0.02)
        s.set_busy("b", False)

    task = asyncio.create_task(release())
    waited = await s.wait_secondaries_idle()
    await task
    assert waited >= 0.015 and s.secondaries_idle


# ── Estimates (the table in the spec) ─────────────────────────────────────────


def _two_lanes(
    primary_s: float,
    secondary_s: float,
    dither_every: int | None,
    primary_n: int = 10,
    secondary_n: int = 10,
):  # type: ignore[no-untyped-def]
    task = make_task(dither_every=dither_every)
    task.lanes = [
        Lane(groups=[ExposureGroup(duration=primary_s, count=primary_n)]),
        Lane(camera_id="cam2", groups=[ExposureGroup(duration=secondary_s, count=secondary_n)]),
    ]
    return task


@pytest.mark.parametrize(
    "primary,secondary,dither,efficiency",
    [
        (600, 120, 1, 1.0),
        (600, 180, 1, 0.9),
        (540, 300, 1, 0.556),
        (300, 300, 3, 1.0),
        (600, 450, None, 1.0),
    ],
)
def test_estimates(primary: float, secondary: float, dither: int | None, efficiency: float) -> None:
    est = estimate_lanes(_two_lanes(primary, secondary, dither), margin_s=0.0)
    assert est[0].primary and est[0].efficiency == 1.0
    assert est[1].efficiency == pytest.approx(efficiency, abs=0.001)
    assert est[1].can_start


def test_estimate_secondary_longer_than_the_dither_interval() -> None:
    est = estimate_lanes(_two_lanes(300, 400, 1), margin_s=10)
    assert est[1].can_start is False


# ── Runs ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    monkeypatch.setattr(lanes_mod, "POLL_S", 0.005)
    r = Rig(tmp_path, SequencerSettings(download_margin_s=0.02, guide_healthy_after_s=0.0))
    r.dm.devices.append(("cam2", "camera"))
    r.imager.real_durations = True
    return r


def _lanes_task(primary: tuple[float, int], secondary: tuple[float, int], **kw: object):  # type: ignore[no-untyped-def]
    task = make_task(**kw)  # type: ignore[arg-type]
    task.lanes = [
        Lane(camera_id="cam1", groups=[ExposureGroup(duration=primary[0], count=primary[1])]),
        Lane(camera_id="cam2", groups=[ExposureGroup(duration=secondary[0], count=secondary[1])]),
    ]
    return task


def _overlaps(log: list[tuple[str, float, float]], camera: str, times: list[float]) -> list[float]:
    return [t for t in times for cam, a, b in log if cam == camera and a < t < b]


async def _run(rig: Rig) -> RunOutcome | None:
    await rig.svc.start()
    return await rig.svc.wait_idle()


async def test_secondary_frames_never_overlap_a_dither(rig: Rig) -> None:
    # primary 0.2 s frames, dither after each; secondary 0.05 s frames fit ~3 per interval
    entry = await rig.svc.add(_lanes_task((0.2, 3), (0.05, 6), dither_every=1))
    assert await _run(rig) == RunOutcome.COMPLETED
    rt = (await rig.svc.get(entry.task.id)).runtime
    assert [lr.groups[0].frames_done for lr in rt.lanes] == [3, 6]
    assert rig.guider.dithers == 2
    assert _overlaps(rig.imager.log, "cam2", rig.guider.dither_times) == []
    cams = {cam for cam, _, _ in rig.imager.log}
    assert cams == {"cam1", "cam2"}
    frames = rig.of("sequencer.frame_saved")
    assert {f.camera_id for f in frames} == {"cam1", "cam2"}


async def test_second_secondary_frame_waits_for_the_dither(rig: Rig) -> None:
    # The spec's example scaled down: primary 0.09 s + dither, secondary wants 2 × 0.05 s:
    # only one fits per interval, the second always waits for the dither.
    await rig.svc.add(_lanes_task((0.09, 3), (0.05, 4), dither_every=1))
    assert await _run(rig) == RunOutcome.COMPLETED
    assert _overlaps(rig.imager.log, "cam2", rig.guider.dither_times) == []
    primary_frames = sorted((a, b) for cam, a, b in rig.imager.log if cam == "cam1")
    secondary_starts = sorted(a for cam, a, _ in rig.imager.log if cam == "cam2")
    for a, b in primary_frames[:-1]:  # while the primary dithers after each frame…
        inside = [s for s in secondary_starts if a <= s < b]
        assert len(inside) <= 1  # …at most one secondary frame per interval
    status = (await rig.svc.get(next(e.task.id for e in rig.svc.entries))).runtime.status
    assert status == TaskStatus.COMPLETED  # the secondary finished after the primary (undithered)


async def test_primary_waits_only_for_download_overruns(rig: Rig) -> None:
    await rig.svc.add(_lanes_task((0.15, 3), (0.04, 6), dither_every=1))
    await _run(rig)
    long_waits = [e for e in rig.of("sequencer.rig_wait") if e.duration_s > 0.2]
    assert long_waits == []


async def test_pause_lets_every_lane_finish_its_frame(rig: Rig) -> None:
    entry = await rig.svc.add(_lanes_task((0.2, 3), (0.2, 3), dither_every=None))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.active == {"cam1", "cam2"})
    await rig.svc.pause("frame")
    await wait_until(lambda: rig.svc.status().run_state == "paused")
    assert rig.of("sequencer.frame_discarded") == []
    rt = (await rig.svc.get(entry.task.id)).runtime
    assert [lr.groups[0].frames_done for lr in rt.lanes] == [1, 1]
    await rig.svc.resume()
    assert await rig.svc.wait_idle() == RunOutcome.COMPLETED


async def test_stop_now_aborts_every_lane(rig: Rig) -> None:
    rig.imager.gate = asyncio.Event()
    entry = await rig.svc.add(_lanes_task((1.0, 2), (1.0, 2), dither_every=None))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.active == {"cam1", "cam2"})
    await rig.svc.stop("now")
    assert await rig.svc.wait_idle() == RunOutcome.STOPPED
    assert len(rig.of("sequencer.frame_discarded")) == 2
    assert (await rig.svc.get(entry.task.id)).runtime.status == TaskStatus.INTERRUPTED


async def test_a_secondary_camera_error_applies_the_error_policy(rig: Rig) -> None:
    rig.imager.fail_camera["cam2"] = RuntimeError("cam2 USB reset")
    entry = await rig.svc.add(_lanes_task((0.2, 2), (0.05, 2), dither_every=None, on_error="skip"))
    await _run(rig)
    rt = (await rig.svc.get(entry.task.id)).runtime
    assert rt.status == TaskStatus.FAILED and "cam2 USB reset" in (rt.last_error or "")


async def test_flip_waits_for_the_secondary_and_it_waits_for_the_flip(rig: Rig) -> None:
    rig.mount.set_ha(0.3)  # past the flip point: the primary flips before its first frame
    await rig.svc.add(_lanes_task((0.05, 2), (0.05, 2), dither_every=None))
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.mount.flips == 1
    flip = rig.mount.flip_times[0]
    assert all(a > flip for cam, a, _ in rig.imager.log)  # nobody exposed before the flip


async def test_autofocus_at_start_on_every_lane(rig: Rig) -> None:
    await rig.svc.add(_lanes_task((0.02, 1), (0.02, 1), dither_every=None, autofocus_at_start=True))
    await _run(rig)
    assert [cam for cam, _ in rig.autofocus.calls] == ["cam1", "cam2"]


async def test_preflight_lane_checks(rig: Rig) -> None:
    await rig.svc.add(_lanes_task((300, 10), (400, 10), dither_every=1))
    codes = {i.code: i.severity for i in (await rig.svc.preflight()).issues}
    assert codes.get("secondary_never_fits") == "error"

    rig2 = rig
    for e in list(rig2.svc.entries):
        await rig2.svc.remove(e.task.id)
    await rig2.svc.add(_lanes_task((540, 10), (300, 12), dither_every=1))
    issues = (await rig2.svc.preflight()).issues
    by_code = {i.code: i for i in issues}
    assert by_code["secondary_efficiency"].severity == "warning"
    assert (
        "56%" in by_code["secondary_efficiency"].message
        or "55%" in by_code["secondary_efficiency"].message
    )
    assert "secondary_outlasts_primary" in by_code


def test_estimate_charges_the_margin_once_per_interval() -> None:
    # 30 s interval, 8 s frames, 3 s allowance: frames start at 0, 8, 16 (16+8+3 ≤ 30) → 3
    est = estimate_lanes(_two_lanes(30, 8, 1), margin_s=3.0)
    assert est[1].efficiency == pytest.approx(24 / 30, abs=0.001)
