"""Centering loop: slew → expose → solve → sync → re-slew until within tolerance."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from astrolol.core.events import EventBus, MountSlewCompleted
from astrolol.plugins.platesolve.centering import CenterRequest, separation_arcsec
from astrolol.plugins.platesolve.models import SolveRequest, SolveResult
from astrolol.plugins.platesolve.solver import SolveManager

TARGET = (83.822, -5.391)


class FakeMount:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.calls: list[str] = []
        self.fail_slew = False

    async def set_target(
        self, mount_id: str, coord: Any, name: str | None = None, source: str | None = None
    ) -> None:
        self.calls.append(f"target:{name}")

    async def slew(self, mount_id: str) -> None:
        if self.fail_slew:
            raise ValueError("below the horizon limit")
        self.calls.append("slew")
        await self.bus.publish(MountSlewCompleted(device_id=mount_id, ra=0.0, dec=0.0))

    async def sync(self, mount_id: str, coord: Any) -> None:
        self.calls.append(f"sync:{coord.ra.deg:.3f}")


class FakeImager:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def expose(self, camera_id: str, req: Any) -> Any:
        self.requests.append(req)
        return SimpleNamespace(fits_path="/tmp/center.fits")


def _solution(ra: float, dec: float) -> SolveResult:
    return SolveResult(ra=ra, dec=dec, rotation=0, pixel_scale=1.0, field_w=1, field_h=1)


def _manager(
    solutions: list[SolveResult | Exception],
) -> tuple[SolveManager, FakeMount, FakeImager]:
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    app = SimpleNamespace(
        state=SimpleNamespace(
            mount_manager=mount,
            imager_manager=imager,
            active_profile=None,
            device_manager=None,
            profile_store=None,
        )
    )
    mgr = SolveManager(event_bus=bus)
    mgr.attach_app(app)
    queue = list(solutions)

    async def fake_solve(req: SolveRequest, job_id: str) -> SolveResult:
        assert (req.ra_hint, req.dec_hint) == TARGET
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    mgr._solve = fake_solve  # type: ignore[method-assign]
    return mgr, mount, imager


def _req(**kw: Any) -> dict[str, Any]:
    return dict(mount_id="m1", camera_id="c1", ra=TARGET[0], dec=TARGET[1], name="M 42", **kw)


def test_separation() -> None:
    assert separation_arcsec(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0, abs=1e-6)
    assert separation_arcsec(10.0, 0.0, 10.0, 1.0) == pytest.approx(3600.0)


async def test_converges_after_one_correction() -> None:
    off = _solution(TARGET[0] + 0.1, TARGET[1])  # ~6 arcmin off
    on = _solution(TARGET[0] + 0.001, TARGET[1])  # ~3.6 arcsec
    mgr, mount, imager = _manager([off, on])
    result = await mgr.center(**_req(tolerance_arcsec=30))
    assert result.success
    assert len(result.attempts) == 2
    assert result.attempts[0].error_arcsec == pytest.approx(358.4, abs=1)
    assert result.final_error_arcsec is not None and result.final_error_arcsec < 30
    # slew first, then sync to where we actually were and slew again
    assert mount.calls == ["target:M 42", "slew", "sync:83.922", "target:M 42", "slew"]
    assert all(r.save is False and r.binning == 2 for r in imager.requests)


async def test_no_slew_first() -> None:
    mgr, mount, _ = _manager([_solution(*TARGET)])
    result = await mgr.center(**_req(slew_first=False))
    assert result.success
    assert mount.calls == []


async def test_no_solution_is_reported_as_such() -> None:
    mgr, mount, _ = _manager([RuntimeError("no stars"), RuntimeError("no stars")])
    result = await mgr.center(**_req(max_attempts=2, slew_first=False))
    assert not result.success
    assert result.failure == "no_solution"
    assert "no stars" in (result.message or "")
    assert mount.calls == []  # nothing to sync to


async def test_not_converged() -> None:
    off = _solution(TARGET[0] + 0.1, TARGET[1])
    mgr, _, _ = _manager([off, off, off])
    result = await mgr.center(**_req(max_attempts=3, slew_first=False))
    assert not result.success
    assert result.failure == "not_converged"
    assert result.final_error_arcsec is not None and result.final_error_arcsec > 300


async def test_mount_error_raises() -> None:
    mgr, mount, _ = _manager([])
    mount.fail_slew = True
    with pytest.raises(ValueError):
        await mgr.center(**_req())


async def test_background_run_and_cancel() -> None:
    mgr, _, imager = _manager([_solution(*TARGET)])
    gate = asyncio.Event()
    original = imager.expose

    async def slow_expose(camera_id: str, req: Any) -> Any:
        await gate.wait()
        return await original(camera_id, req)

    imager.expose = slow_expose  # type: ignore[method-assign]
    run = await mgr.start_center(CenterRequest(**_req(slew_first=False)))
    assert run.status == "running"
    with pytest.raises(ValueError):
        await mgr.start_center(CenterRequest(**_req()))
    await mgr.cancel_center()
    current = mgr.center_run()
    assert current is not None and current.status == "cancelled"


async def test_background_run_completes() -> None:
    mgr, _, _ = _manager([_solution(*TARGET)])
    await mgr.start_center(CenterRequest(**_req(slew_first=False)))
    assert mgr._center_task is not None
    await mgr._center_task
    current = mgr.center_run()
    assert current is not None and current.status == "completed"
    assert current.result is not None and current.result.success
