"""Wizard orchestration tests: state-machine behaviour (slew/solve order, precondition
checks, retries, cancellation), not the fitting math itself -- that's test_solver.py's
job (38 tests against an independent oracle). Here, a perfectly-aligned fake mount is
used so a correct run's final alt/az error comes out near zero; that's enough to confirm
the JNow conversion and Observation-building path works end to end without duplicating
solver.py's own extensive correctness coverage.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from astrolol.core.events import EventBus, MountSlewCompleted
from astrolol.mount.sky import icrs_to_jnow
from plugins.polar_align.wizard import PolarAlignWizard, WizardEngine, WizardRequest, WizardRun

LATITUDE = 45.0
LONGITUDE = 5.0
START_RA_H = 10.0
START_DEC_DEG = 20.0  # 30 lands the fitted axis's bearing in update_pole_offset's symmetric-plane guard


class FakeMount:
    """A perfectly-aligned mount: slewing to a target lands exactly on it."""

    def __init__(self, bus: EventBus, start_ra_h: float = START_RA_H, start_dec_deg: float = START_DEC_DEG) -> None:
        self.bus = bus
        self.ra_h = start_ra_h
        self.dec_deg = start_dec_deg
        self.pier_side = "West"
        self.slew_count = 0
        self._target: Any = None
        self.fail_on_slew: int | None = None  # 1-indexed slew number to fail, if set

    async def set_target(self, mount_id: str, coord: Any, name: str | None = None, source: str | None = None) -> None:
        self._target = coord

    async def slew(self, mount_id: str) -> None:
        self.slew_count += 1
        if self.fail_on_slew == self.slew_count:
            raise ValueError("simulated slew failure")
        self.ra_h = self._target.ra.hour
        self.dec_deg = self._target.dec.deg
        await self.bus.publish(MountSlewCompleted(device_id=mount_id, ra=self.ra_h, dec=self.dec_deg))

    async def get_status(self, mount_id: str) -> SimpleNamespace:
        when = datetime.now(timezone.utc)
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


def _site_fixtures(tmp_path):
    from astrolol.equipment.models import SiteItem
    from astrolol.equipment.store import EquipmentStore
    from astrolol.profiles.models import Profile, ProfileNode

    store = EquipmentStore(tmp_path / "inventory.json")
    site = store.create(SiteItem(name="Test Site", latitude=LATITUDE, longitude=LONGITUDE, altitude=0.0))
    profile = Profile(name="p", roots=[ProfileNode(item_id=site.id)])
    return profile, store


def _req(**kw: Any) -> WizardRequest:
    return WizardRequest(mount_id="m1", camera_id="c1", exposure_s=1.0, binning=1, step_deg=45.0, **kw)


@pytest.mark.asyncio
async def test_happy_path_completes_with_near_zero_error(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
    await wizard.run(run)

    # Not "completed": the wizard's own job (the fit) is done, but the run stays
    # "converging" until the user says they're satisfied -- see finish_converging.
    assert run.status == "converging", run.error
    assert len(run.points) == 3
    assert mount.slew_count == 3
    assert imager.expose_count == 3
    assert run.result is not None
    # A few arcmin, not ~0: converting each solved point's ICRS to JNow *independently*
    # (required, since that's what a real plate solve returns) is not itself a rigid
    # rotation across different sky positions, so even a perfectly-aligned mount shows a
    # small spurious fitted error from this alone -- confirmed by feeding hand-built,
    # perfectly self-consistent data through fit_pole_offset directly (gives <0.01', see
    # the investigation that landed this comment) and comparing to this same data with
    # only the per-point JNow dec varying as it legitimately does here. Same ballpark as
    # the other accepted precision floors in this plugin (ASTAP's own ~10-20" solve noise,
    # sky.alt_az's precession-free simplification) -- fine at the wizard's arcminute-level
    # target precision.
    assert run.result.alt_error_arcmin == pytest.approx(0.0, abs=4.0)
    assert run.result.az_error_arcmin == pytest.approx(0.0, abs=4.0)


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
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
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
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
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
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
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
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
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
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
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
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
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
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
    await wizard.run(run)

    assert run.status == "failed"
    assert "Dec drifted" in (run.error or "")


@pytest.mark.asyncio
async def test_horizon_violation_fails_before_any_slew(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    # Start pointed such that a 45deg step plants a point below the horizon at this site.
    mount = FakeMount(bus, start_ra_h=0.0, start_dec_deg=-40.0)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
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


@pytest.mark.asyncio
async def test_recheck_updates_live_offset(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
    await wizard.run(run)
    assert run.status == "converging", run.error
    assert run.live_offset is None

    expose_count_before = imager.expose_count
    await wizard.recheck(run)

    assert run.status == "converging"  # a recheck doesn't end the run
    assert run.live_offset is not None
    # The fake mount hasn't actually moved (no knob turn simulated), so the live
    # reading should land close to the original fit's own result.
    assert run.live_offset.alt_error_arcmin == pytest.approx(run.result.alt_error_arcmin, abs=1.0)
    assert run.live_offset.az_error_arcmin == pytest.approx(run.result.az_error_arcmin, abs=1.0)
    # Exactly one extra expose, and it used the tight recheck hint/radius, not the
    # main fit's defaults -- confirms the "reuse the reference, don't re-slew or
    # re-establish from scratch" design.
    assert imager.expose_count == expose_count_before + 1
    last_solve_call = solve_manager.solve_calls[-1]
    assert last_solve_call["radius"] == run.request.converge_search_radius_deg
    assert last_solve_call["ra_hint"] == pytest.approx(run.points[-1].solved_ra_hours * 15.0)


@pytest.mark.asyncio
async def test_recheck_rejects_when_not_converging(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
    # Never run -- still "running", not "converging".
    with pytest.raises(ValueError, match="converging"):
        await wizard.recheck(run)


@pytest.mark.asyncio
async def test_finish_converging_marks_completed(tmp_path) -> None:
    profile, store = _site_fixtures(tmp_path)
    bus = EventBus()
    mount = FakeMount(bus)
    imager = FakeImager()
    solve_manager = FakeSolveManager(mount)
    app = _app(mount, imager, solve_manager, profile=profile, equipment_store=store)

    wizard = PolarAlignWizard(app, bus)
    run = WizardRun(id="r1", request=_req(), started_at=datetime.now(timezone.utc))
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
    await asyncio.sleep(0.2)  # let the background task reach "converging"
    assert engine.current_run is not None
    assert engine.current_run.status == "converging"

    returned = await engine.recheck()
    assert returned is run  # same object engine tracks as current_run
    assert run.live_offset is not None


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
    await asyncio.sleep(0.2)
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
    await asyncio.sleep(0.2)
    assert engine.current_run.status == "converging"

    with pytest.raises(ValueError, match="converging"):
        await engine.start(_req())

    await engine.cancel()  # clean up
