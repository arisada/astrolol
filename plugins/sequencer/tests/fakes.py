"""Fake managers for sequencer tests — no hardware, controllable timing and failures."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from astrolol.core.events import (
    EventBus,
    MountMeridianFlipCompleted,
    MountParked,
    MountSlewCompleted,
)
from astrolol.core.guiding import (
    GuiderNotConnected,
    GuiderStatus,
    GuidingHealth,
    GuidingStats,
    SettleFailed,
    SettleParams,
)
from astrolol.core.sequencer.models import ExposureGroup, ImagingTask, Lane, TargetRef
from plugins.sequencer.service import SequencerServiceImpl
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.store import QueueStore
from tests.conftest import make_fake_fits


async def wait_until(cond: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.002)


class FakeImager:
    def __init__(self, frames_dir: Path) -> None:
        self.frames_dir = frames_dir
        self.requests: list[tuple[str, Any]] = []
        self.fail_next: list[Exception] = []
        self.fail_camera: dict[str, Exception] = {}   # camera_id → error on its next exposure
        self.gate: asyncio.Event | None = None  # when set: exposures wait for it
        self.real_durations = False             # sleep the requested duration
        self.active: set[str] = set()
        self.log: list[tuple[str, float, float]] = []   # (camera, start, end), monotonic
        self.cancelled = 0
        self.saved = 0

    @property
    def exposing(self) -> bool:
        return bool(self.active)

    async def expose(self, camera_id: str, req: Any) -> Any:
        self.requests.append((camera_id, req))
        if camera_id in self.fail_camera:
            raise self.fail_camera.pop(camera_id)
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.active.add(camera_id)
        start = time.monotonic()
        try:
            if self.gate is not None:
                await self.gate.wait()
            elif self.real_durations:
                await asyncio.sleep(req.duration)
            else:
                await asyncio.sleep(0.003)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active.discard(camera_id)
        self.log.append((camera_id, start, time.monotonic()))
        self.saved += 1
        path = self.frames_dir / f"frame_{self.saved}.fits"
        make_fake_fits(path, width=8, height=8)
        return SimpleNamespace(fits_path=str(path))


class FakeMountManager:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self.ha0 = -2.0
        self.ha_speed = 0.0  # hours of HA per real second
        self._t0 = time.monotonic()
        self.pier: str | None = "West"
        self.parked = False
        self.ra_h = 1.0
        self.dec = 40.0
        self.slews: list[tuple[float, float, str | None]] = []
        self.flips = 0
        self.flip_times: list[float] = []
        self.fail_slew: list[str] = []
        self.suspended = 0
        self.events: list[str] = []

    def set_ha(self, ha: float, speed: float = 0.0) -> None:
        self.ha0, self.ha_speed, self._t0 = ha, speed, time.monotonic()

    @property
    def ha(self) -> float:
        return self.ha0 + (time.monotonic() - self._t0) * self.ha_speed

    async def get_status(self, mount_id: str) -> Any:
        return SimpleNamespace(
            hour_angle=self.ha,
            pier_side=self.pier,
            is_parked=self.parked,
            ra=self.ra_h,
            dec=self.dec,
        )

    async def set_target(
        self, mount_id: str, coord: Any, name: str | None = None, source: str | None = None
    ) -> None:
        self._target = (coord.ra.deg, coord.dec.deg, name)

    async def slew(self, mount_id: str) -> None:
        if self.fail_slew:
            raise ValueError(self.fail_slew.pop(0))
        self.slews.append(self._target)
        self.ra_h, self.dec = self._target[0] / 15.0, self._target[1]
        self.events.append("slew")
        await self._bus.publish(
            MountSlewCompleted(device_id=mount_id, ra=self._target[0], dec=self._target[1])
        )

    async def meridian_flip(self, mount_id: str) -> None:
        self.flips += 1
        self.flip_times.append(time.monotonic())
        self.pier = "East"
        self.events.append("flip")
        await self._bus.publish(MountMeridianFlipCompleted(device_id=mount_id))

    async def unpark(self, mount_id: str) -> None:
        self.parked = False
        self.events.append("unpark")

    async def park(self, mount_id: str) -> None:
        self.parked = True
        self.events.append("park")
        await self._bus.publish(MountParked(device_id=mount_id))

    @contextlib.contextmanager
    def suspend_auto_flip(self, mount_id: str) -> Iterator[None]:
        self.suspended += 1
        try:
            yield
        finally:
            self.suspended -= 1


class FakeGuider:
    """Implements the core Guider protocol."""

    name = "fake"

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self.connected = True
        self.guiding = False
        self.guides = 0
        self.dithers = 0
        self.stops = 0
        self.settle_error: str | None = None
        self.unguided_s = 0.0
        self.losses = 0
        self.star_lost = False
        self.guiding_for_s = 1e6  # healthy for ages unless a test says otherwise
        self.unguided_for_s = 0.0
        self.fail_guides = 0  # the next N guide() calls fail (not connected)
        self.dither_times: list[float] = []

    def status(self) -> GuiderStatus:
        return GuiderStatus(
            guider=self.name,
            connected=self.connected,
            state="Guiding" if self.guiding else "Stopped",
            guiding=self.guiding,
            active=self.guiding,
        )

    def health(self) -> GuidingHealth:
        if self.guiding and not self.star_lost:
            return GuidingHealth(guiding=True, guiding_for_s=self.guiding_for_s)
        return GuidingHealth(
            guiding=False,
            unguided_for_s=self.unguided_for_s,
            reason="star_lost" if self.guiding else "stopped",
        )

    def mark(self) -> float:
        return time.monotonic()

    def stats(self, since: float, until: float | None = None) -> GuidingStats:
        return GuidingStats(
            duration_s=1.0, steps=1, rms_total=0.8, unguided_s=self.unguided_s, losses=self.losses
        )

    async def guide(
        self, settle: SettleParams, *, recalibrate: bool = False, wait_settle: bool = True
    ) -> None:
        assert wait_settle is True
        self.guides += 1
        if not self.connected or self.fail_guides > 0:
            self.fail_guides = max(0, self.fail_guides - 1)
            raise GuiderNotConnected("fake guider not connected")
        self.guiding = True
        if self.settle_error:
            raise SettleFailed(f"settle failed: {self.settle_error}")

    async def stop(self) -> None:
        self.stops += 1
        self.guiding = False

    async def dither(self, pixels: float, ra_only: bool, settle: SettleParams) -> None:
        self.dithers += 1
        self.dither_times.append(time.monotonic())

    async def pause(self) -> None:
        pass

    async def resume(self) -> None:
        pass


class FakeAutofocus:
    """AutofocusEngine.focus() stand-in: queued results, then success."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.results: list[Any] = []

    async def focus(self, camera_id: str, focuser_id: str) -> Any:
        self.calls.append((camera_id, focuser_id))
        if self.results:
            return self.results.pop(0)
        return SimpleNamespace(
            status="completed",
            error=None,
            sky_problem=False,
            optimal_position=1000,
            data_points=[SimpleNamespace(fwhm=2.5)],
        )


def af_no_stars() -> Any:
    return SimpleNamespace(
        status="failed",
        error="No stars detected",
        sky_problem=True,
        optimal_position=None,
        data_points=[],
    )


class FakeFocuser:
    def __init__(self) -> None:
        self.temperature: float | None = 10.0

    async def get_status(self) -> Any:
        return SimpleNamespace(temperature=self.temperature)


class FakeSolveManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.results: list[Any] = []

    async def center(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.results:
            return self.results.pop(0)
        return SimpleNamespace(
            success=True, failure=None, attempts=[1], final_error_arcsec=12.0, message=None
        )


class FakeFilterWheelManager:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.slot: int | None = 1
        self.selected: list[int] = []

    async def get_status(self, fw_id: str) -> Any:
        return SimpleNamespace(filter_names=self.names, current_slot=self.slot)

    async def select_filter(self, fw_id: str, slot: int) -> None:
        self.selected.append(slot)
        self.slot = slot


class FakeDeviceManager:
    def __init__(self, devices: list[tuple[str, str]]) -> None:
        self.devices = devices  # (device_id, kind)
        self.focuser = FakeFocuser()

    def get_focuser(self, device_id: str) -> FakeFocuser:
        return self.focuser

    def list_connected(self) -> list[dict[str, str]]:
        return [{"device_id": d, "kind": k} for d, k in self.devices]


class Rig:
    """A fake app wired with every manager the sequencer can use."""

    def __init__(self, tmp_path: Path, settings: SequencerSettings | None = None) -> None:
        self.bus = EventBus()
        self.imager = FakeImager(tmp_path / "frames")
        self.mount = FakeMountManager(self.bus)
        self.guider = FakeGuider(self.bus)
        self.solver = FakeSolveManager()
        self.fwm = FakeFilterWheelManager(["L", "R", "G", "B", "Ha"])
        self.dm = FakeDeviceManager(
            [("cam1", "camera"), ("mount1", "mount"), ("fw1", "filter_wheel"), ("foc1", "focuser")]
        )
        self.autofocus = FakeAutofocus()
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                device_manager=self.dm,
                imager_manager=self.imager,
                mount_manager=self.mount,
                filter_wheel_manager=self.fwm,
                guider=self.guider,
                solve_manager=self.solver,
                autofocus_engine=self.autofocus,
                active_profile=None,
                equipment_store=None,
            )
        )
        self.store_path = tmp_path / "sequencer_queue.json"
        self.settings = settings or SequencerSettings()
        self.svc = SequencerServiceImpl(
            self.app, self.bus, self.settings, QueueStore(self.store_path)
        )
        self.events: list[Any] = []
        self._q = self.bus.subscribe()

    def drain(self) -> list[Any]:
        while not self._q.empty():
            self.events.append(self._q.get_nowait())
        return self.events

    def of(self, type_: str) -> list[Any]:
        return [e for e in self.drain() if e.type == type_]

    def reload(self) -> SequencerServiceImpl:
        """A fresh service on the same store (simulated restart)."""
        return SequencerServiceImpl(self.app, self.bus, self.settings, QueueStore(self.store_path))


def make_task(
    name: str = "M 42",
    groups: list[ExposureGroup] | None = None,
    *,
    ra: float | None = 83.8,
    dec: float | None = -5.4,
    kind: str = "coordinates",
    **kwargs: Any,
) -> ImagingTask:
    target = TargetRef(kind=kind, name=name, ra=ra, dec=dec)  # type: ignore[arg-type]
    return ImagingTask(
        target=target,
        lanes=[Lane(groups=groups or [ExposureGroup(duration=1.0, count=2)])],
        **kwargs,
    )
