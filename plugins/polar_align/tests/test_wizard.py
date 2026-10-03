"""Wizard orchestration tests: state-machine behaviour (planning, slew/solve order,
precondition checks, retries, cancellation, CONVERGING rechecks), not the fitting math
itself -- that's test_solver.py's job (against an independent oracle). Here, a
perfectly-aligned fake mount is used, so a correct run's final alt/az error comes out at
~zero; that's enough to confirm the planning, JNow conversion and Observation-building
path works end to end.

Time is frozen and advanced explicitly (the ``clock`` fixture, autouse): each slew takes
a minute and each exposure its own duration, like a real run -- and nothing depends on
what time of day pytest happens to run at (it used to: wall-clock time made three of the
CONVERGING tests mutually exclusive depending on the hour).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import plugins.polar_align.wizard as wizard_module
from astrolol.core.events import EventBus, MountSlewCompleted
from astrolol.mount.sky import icrs_to_jnow, local_sidereal_time_h
from plugins.polar_align.solver import reference_conditioning_margin_deg
from plugins.polar_align.wizard import (
    AUTO_DEC_CANDIDATES_DEG,
    PolarAlignWizard,
    WizardEngine,
    WizardRequest,
    WizardRun,
    plan_targets,
)

LATITUDE = 45.0
LONGITUDE = 5.0
START_RA_H = 10.0
START_DEC_DEG = 20.0
T0 = datetime(2026, 10, 1, 21, 0, 0, tzinfo=timezone.utc)
SLEW_DURATION_S = 60.0


class Clock:
    """Stands in for wizard._now: frozen unless advanced."""

    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock(T0)
    monkeypatch.setattr(wizard_module, "_now", c)
    return c


def _clock() -> Clock:
    return wizard_module._now  # type: ignore[return-value]


class FakeMount:
    """A perfectly-aligned, tracking mount: slewing to a target lands exactly on it, and it
    holds that (ICRS) position from then on. Takes SLEW_DURATION_S of clock time per slew."""

    def __init__(self, bus: EventBus, start_ra_h: float = START_RA_H, start_dec_deg: float = START_DEC_DEG) -> None:
        self.bus = bus
        self.ra_h = start_ra_h
        self.dec_deg = start_dec_deg
        self.pier_side = "West"
        self.slew_count = 0
        self._target: Any = None
        self.fail_on_slew: int | None = None  # 1-indexed slew number to fail, if set
        self.dec_jnow_after_slew: list[float] = []

    async def set_target(self, mount_id: str, coord: Any, name: str | None = None, source: str | None = None) -> None:
        self._target = coord

    async def slew(self, mount_id: str) -> None:
        self.slew_count += 1
        if self.fail_on_slew == self.slew_count:
            raise ValueError("simulated slew failure")
        clock = _clock()
        if isinstance(clock, Clock):
            clock.advance(SLEW_DURATION_S)
        self.ra_h = self._target.ra.hour
        self.dec_deg = self._target.dec.deg
        self.dec_jnow_after_slew.append((await self.get_status(mount_id)).dec_jnow)
        await self.bus.publish(MountSlewCompleted(device_id=mount_id, ra=self.ra_h, dec=self.dec_deg))

    async def get_status(self, mount_id: str) -> SimpleNamespace:
        when = _clock()()
        from astropy.coordinates import SkyCoord
        import astropy.units as u

        coord = SkyCoord(ra=self.ra_h * u.hourangle, dec=self.dec_deg * u.deg, frame="icrs")
        ra_jnow, dec_jnow = icrs_to_jnow(coord, when)
        return SimpleNamespace(
            is_slewing=False, pier_side=self.pier_side,
            ra=self.ra_h, dec=self.dec_deg, ra_jnow=ra_jnow, dec_jnow=dec_jnow,
        )


class FakeImager:
    def __init__(self) -> None:
        self.expose_count = 0

    async def expose(self, camera_id: str, req: Any) -> SimpleNamespace:
        self.expose_count += 1
        clock = _clock()
        if isinstance(clock, Clock):
            clock.advance(req.duration)
        return SimpleNamespace(fits_path=f"/tmp/polar_align_{self.expose_count}.fits")


class FakeSolveManager:
    """Solves perfectly: returns the mount's own current ICRS position, every time --
    i.e. zero misalignment, zero solve noise."""

    def __init__(self, mount: FakeMount) -> None:
        self.mount = mount
        self.solve_calls: list[dict] = []
        self.fail_count = 0  # number of times to raise before succeeding, per call

    async def solve(self, **kwargs: Any) -> SimpleNamespace:
        self.solve_calls.append(kwargs)
        if self.fail_count > 0:
            self.fail_count -= 1
            raise RuntimeError("simulated solve failure")
        return SimpleNamespace(
            ra=self.mount.ra_h * 15.0, dec=self.mount.dec_deg,
            rotation=0.0, pixel_scale=1.0, field_w=1.0, field_h=1.0, duration_ms=100,
        )


def _app(mount: FakeMount, imager: FakeImager, solve_manager: Any, *, site: Any = None, profile: Any = None,
          equipment_store: Any = None, profile_store: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            mount_manager=mount, imager_manager=imager, solve_manager=solve_manager,
            active_profile=profile, equipment_store=equipment_store, profile_store=profile_store,
        )
    )


def _site_fixtures(tmp_path, latitude: float = LATITUDE):
    from astrolol.equipment.models import SiteItem
    from astrolol.equipment.store import EquipmentStore
    from astrolol.profiles.models import Profile, ProfileNode

    store = EquipmentStore(tmp_path / "inventory.json")
    site = store.create(SiteItem(name="Test Site", latitude=latitude, longitude=LONGITUDE, altitude=0.0))
    profile = Profile(name="p", roots=[ProfileNode(item_id=site.id)])
    return profile, store


def _req(**kw: Any) -> WizardRequest:
    kw.setdefault("settle_s", 0.0)
    return WizardRequest(mount_id="m1", camera_id="c1", exposure_s=1.0, binning=1, **kw)


async def _wait_until(predicate: Any, timeout: float = 2.0) -> None:
    """Poll in real time until predicate() is true -- a fixed `asyncio.sleep(0.2)` to
    "let the background task reach converging" is a real-time race against the fakes'
    own awaits (expose/solve/slew), not the frozen `clock` fixture (which only controls
    timestamps computed via wizard._now, not actual wall-clock scheduling), so it's
    flaky under any system load. Fails fast via the predicate instead of hoping 0.2s
    was enough."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() >= deadline:
            raise AssertionError(f"Condition not met within {timeout}s")
        await asyncio.sleep(0.01)


def _ha_of(ra_jnow_h: float, when: datetime) -> float:
    return (local_sidereal_time_h(when, LONGITUDE) - ra_jnow_h + 12.0) % 24.0 - 12.0


@pytest.mark.asyncio
async def test_happy_path_completes_with_near_zero_error(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    # Not "completed": the wizard's own job (the fit) is done, but the run stays
    # "converging" until the user says they're satisfied -- see finish_converging.
    assert run.status == "converging", run.error
    assert len(run.points) == 3
    assert mount.slew_count == 3
    assert imager.expose_count == 3
    assert run.result is not None
    # A perfect mount, with a minute of real time per slew: ~zero. (This used to be "a few
    # arcmin" -- explained away as ICRS->JNow not being a rigid rotation, but it was the
    # plan holding ICRS Dec constant, which moves the mount's real Dec axis by several
    # arcmin between points, plus the fit's sky-vs-Earth frame mix-up once time passes.)
    assert run.result.alt_error_arcmin == pytest.approx(0.0, abs=0.1)
    assert run.result.az_error_arcmin == pytest.approx(0.0, abs=0.1)



@pytest.mark.asyncio
async def test_solve_retries_on_transient_failure(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    solve_manager.fail_count = 1  # first attempt of the whole run fails, then succeeds
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "converging", run.error
    assert len(run.points) == 3
    # One extra expose/solve attempt for the retried point.
    assert imager.expose_count == 4


@pytest.mark.asyncio
async def test_solve_failure_exhausts_retries_and_fails_run(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    solve_manager.fail_count = 10  # always fails
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "failed"
    assert "Plate solve failed" in (run.error or "")
    assert len(run.points) == 0


@pytest.mark.asyncio
async def test_missing_solve_manager_fails_cleanly(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    app = _app(mount, imager, None, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "failed"
    assert "platesolve" in (run.error or "")
    assert mount.slew_count == 0


@pytest.mark.asyncio
async def test_missing_site_fails_cleanly(tmp_path) -> None:
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=None, equipment_store=None)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "failed"
    assert "site" in (run.error or "").lower()
    assert mount.slew_count == 0


@pytest.mark.asyncio
async def test_mount_already_slewing_fails_cleanly(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)

    class BusyMount(FakeMount):
        async def get_status(self, mount_id: str) -> SimpleNamespace:
            status = await super().get_status(mount_id)
            status.is_slewing = True
            return status

    busy_mount = BusyMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(busy_mount)
    app = _app(busy_mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "failed"
    assert "already slewing" in (run.error or "")


@pytest.mark.asyncio
async def test_pier_flip_mid_run_fails_cleanly(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    # Flip pier side after the first slew completes.
    real_slew = mount.slew

    async def slewing_with_flip(mount_id: str) -> None:
        await real_slew(mount_id)
        if mount.slew_count == 1:
            mount.pier_side = "East"

    mount.slew = slewing_with_flip  # type: ignore[method-assign]

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "failed"
    assert "Pier side changed" in (run.error or "")
    assert len(run.points) == 0  # fails before solving the point whose slew tripped it


@pytest.mark.asyncio
async def test_dec_drift_mid_run_fails_cleanly(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    real_slew = mount.slew

    async def slewing_with_dec_nudge(mount_id: str) -> None:
        await real_slew(mount_id)
        if mount.slew_count == 1:
            mount.dec_deg += 0.1  # 6' -- well past the 1' guard

    mount.slew = slewing_with_dec_nudge  # type: ignore[method-assign]

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "failed"
    assert "Dec drifted" in (run.error or "")


@pytest.mark.asyncio
async def test_first_point_goto_error_below_horizon_fails_cleanly(tmp_path) -> None:
    """plan_targets() validates the horizon limit against the PLANNED position before
    anything moves. If the mount's GoTo lands somewhere else entirely -- plausible on
    exactly the badly-misaligned mount this wizard exists to fix -- that validation no
    longer means anything. The first point's *actual* altitude must be re-checked."""
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    real_slew = mount.slew

    async def slew_with_goto_error(mount_id: str) -> None:
        await real_slew(mount_id)
        if mount.slew_count == 1:
            mount.dec_deg -= 120.0  # lands well below the 0deg horizon limit regardless of the plan

    mount.slew = slew_with_goto_error  # type: ignore[method-assign]

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "failed"
    assert "below the" in (run.error or "") and "horizon limit" in (run.error or "")


@pytest.mark.asyncio
async def test_horizon_violation_fails_before_any_slew(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    # Dec -50 never rises at latitude 45: the planner must refuse before anything moves.
    run = WizardRun(id="r1", request=_req(dec_deg=-50.0), started_at=T0)
    await wizard.run(run)

    assert run.status == "failed"
    assert "horizon" in (run.error or "").lower()
    assert mount.slew_count == 0


@pytest.mark.asyncio
async def test_cancellation_mid_run() -> None:
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)

    class SlowMount(FakeMount):
        async def slew(self, mount_id: str) -> None:
            await asyncio.sleep(10)

    slow_mount = SlowMount(bus)

    class Engine(WizardEngine):
        pass

    app = _app(slow_mount, imager, solve_manager, profile=None, equipment_store=None)
    # Give it a real site so it gets past the precondition checks and into the slew.
    from astrolol.equipment.models import SiteItem
    import tempfile
    from pathlib import Path
    from astrolol.equipment.store import EquipmentStore
    from astrolol.profiles.models import Profile, ProfileNode

    with tempfile.TemporaryDirectory() as tmp:
        store = EquipmentStore(Path(tmp) / "inventory.json")
        site = store.create(SiteItem(name="s", latitude=LATITUDE, longitude=LONGITUDE, altitude=0.0))
        app.state.active_profile = Profile(name="p", roots=[ProfileNode(item_id=site.id)])
        app.state.equipment_store = store

        engine = Engine(app, bus)
        run = await engine.start(_req())
        await asyncio.sleep(0.05)  # let it reach the slew
        await engine.cancel()

        assert run.status == "cancelled"


@pytest.mark.asyncio
async def test_engine_rejects_concurrent_start(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()

    class SlowMount(FakeMount):
        async def slew(self, mount_id: str) -> None:
            await asyncio.sleep(10)

    mount = SlowMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    await engine.start(_req())
    with pytest.raises(ValueError):
        await engine.start(_req())
    await engine.cancel()


# ===========================================================================
# CONVERGING phase: recheck() and finish_converging()
# ===========================================================================

# ===========================================================================
# Target planning
# ===========================================================================


@pytest.mark.parametrize("current_ha", [-3.0, -0.1, 0.1, 2.0, 5.0])
@pytest.mark.parametrize("latitude", [45.0, 50.67, -33.0])
def test_plan_targets_stays_on_current_side_with_auto_dec(current_ha: float, latitude: float) -> None:
    plan = plan_targets(latitude, current_ha, 30.0, 3, 0.0)
    side = 1.0 if current_ha >= 0 else -1.0
    assert plan.side == ("west" if side > 0 else "east")
    for h in plan.hour_angles_h:
        assert side * h >= wizard_module.MIN_MERIDIAN_CLEARANCE_H - 1e-9
        assert abs(h) <= wizard_module.MAX_ABS_HA_H + 1e-9
    # Monotonic steps of exactly step_deg, one direction.
    steps = [b - a for a, b in zip(plan.hour_angles_h, plan.hour_angles_h[1:])]
    assert all(abs(abs(d) - 2.0) < 1e-9 for d in steps)
    assert len({d > 0 for d in steps}) == 1
    # Auto Dec comes from the declared band, in the site's hemisphere -- never the pole.
    assert abs(plan.dec_jnow_deg) in AUTO_DEC_CANDIDATES_DEG
    assert (plan.dec_jnow_deg > 0) == (latitude > 0)
    # The last point (the CONVERGING reference) is well-conditioned, now and half an hour on.
    pole = 90.0 if latitude > 0 else -90.0
    for dt in (0.0, 0.5):
        assert reference_conditioning_margin_deg(0.0, pole, plan.hour_angles_h[-1] + dt, plan.dec_jnow_deg, latitude) > 0


def test_plan_targets_honours_dec_override() -> None:
    plan = plan_targets(LATITUDE, 1.0, 30.0, 3, 0.0, dec_deg=20.0)
    assert plan.dec_jnow_deg == 20.0


def test_plan_targets_rejects_impossible_geometry() -> None:
    # Dec -50 never rises at latitude 45.
    with pytest.raises(ValueError, match="horizon"):
        plan_targets(LATITUDE, 1.0, 30.0, 3, 0.0, dec_deg=-50.0)


def test_wizard_request_rejects_near_pole_dec() -> None:
    with pytest.raises(ValueError):
        _req(dec_deg=89.85)


@pytest.mark.asyncio
async def test_mount_parked_at_pole_still_plans_a_sane_dec(tmp_path) -> None:
    """2026-10-01 regression: the mount sat near Dec 90 when the wizard started, and every
    point was planned at that Dec. The plan must not inherit the mount's current Dec."""
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus, start_ra_h=3.0, start_dec_deg=89.85)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "converging", run.error
    assert run.plan is not None
    assert abs(run.plan.dec_jnow_deg) in AUTO_DEC_CANDIDATES_DEG
    assert all(abs(p.solved_dec_deg - run.plan.dec_jnow_deg) < 0.05 for p in run.points)


@pytest.mark.asyncio
@pytest.mark.parametrize("start_ra_h", [0.0, 6.0, 12.0, 18.0])
async def test_points_hold_jnow_dec_and_one_side_of_meridian(tmp_path, start_ra_h: float) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus, start_ra_h=start_ra_h, start_dec_deg=30.0)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    start_status = await mount.get_status("m1")
    start_side = _ha_of(start_status.ra_jnow, T0) >= 0

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)

    assert run.status == "converging", run.error
    # The mount's mechanical (JNow) Dec is the same at every point -- not the ICRS Dec.
    decs = mount.dec_jnow_after_slew
    assert max(decs) - min(decs) < 1.0 / 3600.0
    # Every point on the side of the meridian the mount started on (no pier flip).
    for p in run.points:
        assert (_ha_of(p.mount_ra_hours, p.when) >= 0) == start_side


@pytest.mark.asyncio
async def test_settle_delay_is_applied(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(wizard_module.asyncio, "sleep", fake_sleep)
    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(settle_s=3.0), started_at=T0)
    await wizard.run(run)

    assert run.status == "converging", run.error
    assert sleeps.count(3.0) == 3


# ===========================================================================
# CONVERGING phase: recheck() and finish_converging()
# ===========================================================================


@pytest.mark.asyncio
async def test_recheck_updates_live_offset(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)
    assert run.status == "converging", run.error
    assert run.live_offset is None

    expose_count_before = imager.expose_count
    await wizard.recheck(run)

    assert run.status == "converging"  # a recheck doesn't end the run
    assert run.live_offset is not None
    # The fake mount hasn't moved (no knob turn simulated), so the live reading must land
    # on the original fit's own result.
    assert run.live_offset.alt_error_arcmin == pytest.approx(run.result.alt_error_arcmin, abs=0.05)
    assert run.live_offset.az_error_arcmin == pytest.approx(run.result.az_error_arcmin, abs=0.05)
    # Exactly one extra expose, and it used the tight recheck hint/radius, not the
    # main fit's defaults -- confirms the "reuse the reference, don't re-slew or
    # re-establish from scratch" design.
    assert imager.expose_count == expose_count_before + 1
    last_solve_call = solve_manager.solve_calls[-1]
    assert last_solve_call["radius"] == run.request.converge_search_radius_deg
    reference = run.points[run.convergence_reference_index]
    assert last_solve_call["ra_hint"] == pytest.approx(reference.solved_ra_hours * 15.0)


@pytest.mark.asyncio
async def test_recheck_after_30_minutes_of_tracking_is_stable(tmp_path, clock: Clock) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)
    assert run.status == "converging", run.error

    for _ in range(3):
        clock.advance(10 * 60)
        await wizard.recheck(run)
        assert run.live_offset.alt_error_arcmin == pytest.approx(run.result.alt_error_arcmin, abs=0.05)
        assert run.live_offset.az_error_arcmin == pytest.approx(run.result.az_error_arcmin, abs=0.05)


@pytest.mark.asyncio
async def test_recheck_rejects_when_not_converging(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    # Never run -- still "running", not "converging".
    with pytest.raises(ValueError, match="converging"):
        await wizard.recheck(run)


@pytest.mark.asyncio
@pytest.mark.parametrize("start_ra_h", [0.0, 4.0, 8.0, 12.0, 16.0, 20.0])
async def test_convergence_reference_is_last_point_where_mount_points(tmp_path, start_ra_h: float) -> None:
    """Regression for the 'stuck on the initial fit' bug: the reference used to be the
    best-conditioned of the fit's points, which was often not the one the mount still
    pointed at -- every recheck then compared two pointings 30-90deg apart and failed.
    The reference must be the last point, and a recheck must succeed for any start."""
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus, start_ra_h=start_ra_h, start_dec_deg=40.0)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)
    assert run.status == "converging", run.error
    assert run.convergence_reference_index == len(run.points) - 1
    assert run.plan is not None and run.plan.reference_margin_deg > 0

    await wizard.recheck(run)
    assert run.live_offset is not None


@pytest.mark.asyncio
async def test_finish_converging_marks_completed(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=T0)
    await wizard.run(run)
    assert run.status == "converging"

    await wizard.finish_converging(run)
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_engine_recheck_updates_current_run(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    run = await engine.start(_req())
    await _wait_until(lambda: run.status != "running")
    assert engine.current_run is not None
    assert engine.current_run.status == "converging"

    returned = await engine.recheck()
    assert returned is run  # same object engine tracks as current_run
    assert run.live_offset is not None


@pytest.mark.asyncio
async def test_engine_recheck_failure_is_logged_and_reraised(tmp_path) -> None:
    from structlog.testing import capture_logs

    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    run = await engine.start(_req())
    await _wait_until(lambda: run.status != "running")
    assert run.status == "converging", run.error

    solve_manager.fail_count = 1
    with capture_logs() as logs:
        with pytest.raises(RuntimeError, match="simulated solve failure"):
            await engine.recheck()
    failed = [e for e in logs if e["event"] == "polar_align.recheck_failed"]
    assert failed and failed[0]["log_level"] == "warning"
    assert failed[0]["error"] == "simulated solve failure"
    assert run.status == "converging"  # one bad recheck isn't fatal to the run
    assert run.live_offset is None


@pytest.mark.asyncio
async def test_recheck_records_timestamp_and_clears_a_prior_error(tmp_path) -> None:
    """last_recheck_error/last_recheck_at live on the run itself, not just the raised
    exception -- an auto-refresh failure has no caller watching, so it has to be visible
    to anyone polling GET /wizard instead."""
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    run = await engine.start(_req())
    await _wait_until(lambda: run.status != "running")
    assert run.status == "converging", run.error
    assert run.last_recheck_at is None

    solve_manager.fail_count = 1
    with pytest.raises(RuntimeError):
        await engine.recheck()
    assert run.last_recheck_error == "simulated solve failure"
    first_at = run.last_recheck_at
    assert first_at is not None

    await engine.recheck()
    assert run.last_recheck_error is None  # a later success clears it
    assert run.last_recheck_at is not None and run.last_recheck_at >= first_at


@pytest.mark.asyncio
async def test_auto_refresh_runs_periodically_and_survives_a_bad_reading(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    run = await engine.start(_req())
    await _wait_until(lambda: run.status != "running")
    assert run.status == "converging", run.error

    calls_before = len(solve_manager.solve_calls)
    solve_manager.fail_count = 1  # the first auto-refresh tick fails
    await engine.start_auto_refresh(0.05)
    assert run.auto_refresh_interval_s == 0.05

    try:
        # Several ticks: at least the one bad reading plus later good ones.
        await asyncio.sleep(0.3)
    finally:
        await engine.stop_auto_refresh()

    assert len(solve_manager.solve_calls) > calls_before + 1  # ran on its own, repeatedly
    assert run.live_offset is not None  # recovered after the bad reading
    assert run.last_recheck_error is None
    assert run.auto_refresh_interval_s is None


@pytest.mark.asyncio
async def test_stop_auto_refresh_actually_stops_it(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    run = await engine.start(_req())
    await _wait_until(lambda: run.status != "running")

    await engine.start_auto_refresh(0.05)
    await asyncio.sleep(0.15)
    await engine.stop_auto_refresh()
    assert run.auto_refresh_interval_s is None

    calls_after_stop = len(solve_manager.solve_calls)
    await asyncio.sleep(0.2)
    assert len(solve_manager.solve_calls) == calls_after_stop  # no more ticks


@pytest.mark.asyncio
async def test_cancel_stops_auto_refresh_too(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    run = await engine.start(_req())
    await _wait_until(lambda: run.status != "running")
    await engine.start_auto_refresh(0.05)

    await engine.cancel()
    assert run.status == "completed"
    assert run.auto_refresh_interval_s is None

    calls_after_cancel = len(solve_manager.solve_calls)
    await asyncio.sleep(0.2)
    assert len(solve_manager.solve_calls) == calls_after_cancel  # loop actually stopped


@pytest.mark.asyncio
async def test_start_auto_refresh_rejects_before_converging(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    await engine.start(_req())
    assert engine.current_run.status == "running"  # not converging yet

    with pytest.raises(ValueError, match="converging"):
        await engine.start_auto_refresh(5.0)


@pytest.mark.asyncio
async def test_start_auto_refresh_rejects_without_a_run(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    with pytest.raises(ValueError, match="No polar"):
        await engine.start_auto_refresh(5.0)


@pytest.mark.asyncio
async def test_engine_cancel_during_converging_completes_not_cancels(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    run = await engine.start(_req())
    await _wait_until(lambda: run.status != "running")
    assert run.status == "converging"

    await engine.cancel()
    assert run.status == "completed"  # not "cancelled" -- nothing failed


@pytest.mark.asyncio
async def test_engine_start_rejects_while_converging(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    engine = WizardEngine(app, bus)
    await engine.start(_req())
    await _wait_until(lambda: engine.current_run.status != "running")
    assert engine.current_run.status == "converging"

    with pytest.raises(ValueError, match="converging"):
        await engine.start(_req())

    await engine.cancel()  # clean up
