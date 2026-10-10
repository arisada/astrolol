"""Tests for the EQMOD mount emulator (Phase 1).

These exercise the actual IMount contract MountManager depends on, plus the
reconnect-without-resync persistence design: an astrolol restart (new
instance, same state_key, same simulated hardware) must not lose a
plate-solve sync, but a simulated hardware power cycle must.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from astropy.coordinates import SkyCoord
import astropy.units as u

from astrolol.devices.base.models import TrackingMode
from astrolol.plugins.eqmod import simulator
from astrolol.plugins.eqmod.simulator import EqmodSimMount, simulate_power_cycle


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTROLOL_DATA_DIR", str(tmp_path))


@pytest.fixture(autouse=True)
def _fast_motion(monkeypatch):
    """Slew/nudge take real wall-clock time by design (see simulator.py's
    module docstring — that's the fix for "instant" slew/nudge). Speed the
    timing constants up for tests so they stay fast without changing the
    code paths under test."""
    monkeypatch.setattr(simulator, "_SLEW_RATE_DEG_PER_SEC", 100_000.0)
    monkeypatch.setattr(simulator, "_SLEW_MIN_DURATION", 0.01)
    monkeypatch.setattr(simulator, "_SLEW_STEP_INTERVAL", 0.005)
    monkeypatch.setattr(simulator, "_NUDGE_STEP_INTERVAL", 0.005)


def _coord(ra_deg: float, dec_deg: float) -> SkyCoord:
    return SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")


# --- Basic lifecycle ---

async def test_connect_disconnect_ping() -> None:
    mount = EqmodSimMount()
    assert await mount.ping() is False
    await mount.connect()
    assert await mount.ping() is True
    await mount.disconnect()
    assert await mount.ping() is False


async def test_fresh_mount_starts_parked_facing_north() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    status = await mount.get_status()
    assert status.is_parked is True
    assert status.is_synced is True
    assert status.dec == pytest.approx(90.0, abs=1e-6)


# --- Core operations ---

async def test_slew_updates_position_and_clears_parked() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    await mount.slew(_coord(90.0, 20.0))
    status = await mount.get_status()
    assert status.is_parked is False
    # abs=1e-3, not 1e-6: dec=20 is off the pole and tracking is off, so RA
    # genuinely drifts a tiny amount between _fix_position() and this read.
    assert status.ra == pytest.approx(6.0, abs=1e-3)  # 90 deg = 6h
    assert status.dec == pytest.approx(20.0, abs=1e-6)


async def test_sync_sets_position_and_is_synced() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    await mount.unpark()
    await mount.sync(_coord(45.0, -10.0))
    status = await mount.get_status()
    assert status.is_synced is True
    assert status.dec == pytest.approx(-10.0, abs=1e-6)


async def test_park_unpark() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    await mount.slew(_coord(45.0, -10.0))
    await mount.set_tracking(True)
    await mount.park()
    status = await mount.get_status()
    assert status.is_parked is True
    assert status.is_tracking is False
    assert status.dec == pytest.approx(90.0, abs=1e-6)

    await mount.unpark()
    status = await mount.get_status()
    assert status.is_parked is False


async def test_set_park_position_uses_current_position() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    await mount.slew(_coord(200.0, 5.0))
    await mount.set_park_position()
    await mount.slew(_coord(10.0, 10.0))
    await mount.park()
    status = await mount.get_status()
    # abs=1e-3: this park position is off the pole (dec=5), so RA drifts a
    # tiny amount between _fix_position() and this read — see the slew test.
    assert status.ra == pytest.approx((200.0 / 15.0), abs=1e-3)
    assert status.dec == pytest.approx(5.0, abs=1e-6)


async def test_set_tracking_with_mode() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    await mount.set_tracking(True, TrackingMode.LUNAR)
    status = await mount.get_status()
    assert status.is_tracking is True
    assert mount._tracking_mode == TrackingMode.LUNAR


async def test_start_move_nudges_then_stop_move() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    await mount.slew(_coord(180.0, 0.0))
    before = await mount.get_status()
    await mount.start_move("N", "centering")
    await asyncio.sleep(0.05)  # let the nudge background task tick at least once
    await mount.stop_move()
    after = await mount.get_status()
    assert after.dec > before.dec
    assert after.is_parked is False


async def test_meridian_flip_toggles_pier_side() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    first = mount._pier_side
    await mount.meridian_flip()
    assert mount._pier_side != first


# --- Sidereal drift while untracked (uses a monkeypatched clock, not real sleep) ---

def _fake_clock(monkeypatch):
    """Install a controllable fake for simulator._now(); returns a [datetime] box
    so the test can advance it by mutating box[0]."""
    box = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(simulator, "_now", lambda: box[0])
    return box


async def test_drift_when_untracked_and_not_at_pole(monkeypatch) -> None:
    clock = _fake_clock(monkeypatch)
    mount = EqmodSimMount()
    await mount.connect()
    await mount.unpark()
    await mount.sync(_coord(180.0, 45.0))  # tracking off by default

    clock[0] += timedelta(hours=1)
    status = await mount.get_status()

    # An untracked mount holds a fixed hour angle, so ICRS RA drifts forward
    # at the sidereal rate (~15.041 deg/hour) while Dec stays put.
    expected_ra_deg = (180.0 + simulator._SIDEREAL_DEG_PER_SEC * 3600.0) % 360.0
    assert status.ra * 15.0 == pytest.approx(expected_ra_deg, abs=1e-6)
    assert status.dec == pytest.approx(45.0, abs=1e-9)


async def test_no_drift_while_tracking(monkeypatch) -> None:
    clock = _fake_clock(monkeypatch)
    mount = EqmodSimMount()
    await mount.connect()
    await mount.unpark()
    await mount.sync(_coord(180.0, 45.0))
    await mount.set_tracking(True)

    before = await mount.get_status()
    clock[0] += timedelta(hours=2)
    after = await mount.get_status()

    assert after.ra == pytest.approx(before.ra, abs=1e-9)
    assert after.dec == pytest.approx(before.dec, abs=1e-9)


async def test_ra_drifts_at_the_pole_too_when_untracked(monkeypatch) -> None:
    """A parked (dec=90), untracked mount's reported RA still drifts with
    time — the pole only makes the *sky direction* independent of RA, not
    the RA number a real driver computes as LST - fixed_hour_angle. Dec
    itself never drifts, at the pole or anywhere else."""
    clock = _fake_clock(monkeypatch)
    mount = EqmodSimMount()
    await mount.connect()  # parked, facing the pole (dec=90), tracking off

    before = await mount.get_status()
    clock[0] += timedelta(hours=5)
    after = await mount.get_status()

    assert after.dec == pytest.approx(90.0, abs=1e-9)
    assert after.ra != before.ra
    expected_ra_deg = (before.ra * 15.0 + simulator._SIDEREAL_DEG_PER_SEC * 5 * 3600.0) % 360.0
    assert after.ra * 15.0 == pytest.approx(expected_ra_deg, abs=1e-6)


# --- Live coordinate push (set_coords_listener — what the WebSocket UI relies on) ---

async def test_coords_listener_fires_immediately_on_registration() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    calls = []
    mount.set_coords_listener(lambda *args: calls.append(args))
    assert len(calls) == 1
    _ra, dec, _ra_jnow, _dec_jnow, _alt, _az, _pier, _ha, _lst, _tracking, parked = calls[0]
    assert dec == pytest.approx(90.0, abs=1e-6)
    assert parked is True


async def test_coords_listener_fires_after_slew() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    calls = []
    mount.set_coords_listener(lambda *args: calls.append(args))
    calls.clear()  # drop the immediate-registration call

    await mount.slew(_coord(45.0, 10.0))

    # A real slew pushes intermediate positions too (see module docstring —
    # that's the fix for "instant" slew), so at least one call is guaranteed
    # but not exactly one; the final call must land on the target.
    assert len(calls) >= 1
    assert calls[-1][1] == pytest.approx(10.0, abs=1e-6)  # dec


async def test_coords_listener_cleared_stops_pushes() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    calls = []
    mount.set_coords_listener(lambda *args: calls.append(args))
    mount.set_coords_listener(None)
    calls.clear()

    await mount.slew(_coord(45.0, 10.0))

    assert calls == []


async def test_disconnect_cancels_coords_pump_task() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    task = mount._coords_task
    assert task is not None and not task.done()

    await mount.disconnect()

    assert task.done()


# --- Location-aware Alt/Az/HA/LST (needs set_location — see module docstring) ---

async def test_alt_az_ha_lst_absent_without_location() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    status = await mount.get_status()
    assert status.alt is None
    assert status.az is None
    assert status.hour_angle is None
    assert status.lst is None


async def test_set_location_populates_alt_az_ha_lst() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    await mount.unpark()
    await mount.sync(_coord(180.0, 45.0))
    await mount.set_location(48.85, 2.35, 35.0)  # Paris

    status = await mount.get_status()
    assert status.alt is not None
    assert status.az is not None
    assert status.lst is not None
    assert status.hour_angle is not None
    assert -12.0 <= status.hour_angle <= 12.0


async def test_set_time_utc_is_a_harmless_noop() -> None:
    """Exists so MountManager.push_site_data()'s hasattr check finds it, like
    IndiMount — see the method docstring for why there's nothing to do."""
    mount = EqmodSimMount()
    await mount.connect()
    await mount.set_time_utc()


# --- Realistic (non-instant) motion ---

async def test_fresh_park_ra_seeded_from_sidereal_time_not_zero() -> None:
    """Guards against the old hardcoded park_ra=0.0 default, which made a
    fresh mount's RA look frozen/unseeded regardless of time of day."""
    mount = EqmodSimMount()
    await mount.connect()
    status = await mount.get_status()
    assert status.ra != pytest.approx(0.0, abs=1e-6)


async def test_slew_takes_measurable_time_at_the_real_rate(monkeypatch) -> None:
    """Overrides this module's autouse speed-up fixture for just this test,
    to confirm slew isn't instantaneous at the actual configured rate."""
    monkeypatch.setattr(simulator, "_SLEW_RATE_DEG_PER_SEC", 3.0)
    monkeypatch.setattr(simulator, "_SLEW_MIN_DURATION", 0.3)
    monkeypatch.setattr(simulator, "_SLEW_STEP_INTERVAL", 0.1)

    mount = EqmodSimMount()
    await mount.connect()
    loop = asyncio.get_event_loop()
    start = loop.time()
    await mount.slew(_coord(0.0, 90.0))  # same as the fresh-connect position -> hits the duration floor
    elapsed = loop.time() - start
    assert elapsed >= simulator._SLEW_MIN_DURATION


# --- Device-specific escape hatch (not part of IMount) ---

async def test_led_brightness_get_set() -> None:
    mount = EqmodSimMount()
    assert mount.get_led_brightness() == 50
    await mount.set_led_brightness(10)
    assert mount.get_led_brightness() == 10


# --- Reconnect-without-resync persistence ---

async def test_sync_survives_astrolol_restart() -> None:
    """A brand new instance (simulating a fresh process) with the same
    state_key must recover the previous sync — the simulated hardware never
    lost power, so there's no reason to distrust it."""
    mount_a = EqmodSimMount(state_key="rig1")
    await mount_a.connect()
    await mount_a.unpark()
    await mount_a.sync(_coord(123.0, 33.0))
    await mount_a.set_tracking(True, TrackingMode.SIDEREAL)

    mount_b = EqmodSimMount(state_key="rig1")
    await mount_b.connect()
    status = await mount_b.get_status()
    assert status.is_synced is True
    assert status.dec == pytest.approx(33.0, abs=1e-6)
    assert status.is_tracking is True


async def test_power_cycle_invalidates_sync_when_not_parked() -> None:
    mount_a = EqmodSimMount(state_key="rig2")
    await mount_a.connect()
    await mount_a.unpark()
    await mount_a.sync(_coord(123.0, 33.0))
    await mount_a.set_tracking(True)

    simulate_power_cycle("rig2")

    mount_b = EqmodSimMount(state_key="rig2")
    await mount_b.connect()
    status = await mount_b.get_status()
    assert status.is_synced is False
    assert status.ra is None
    assert status.dec is None
    assert status.is_tracking is False


async def test_power_cycle_while_parked_is_still_trusted() -> None:
    """A power cycle while parked is safe to trust — the mount is held at a
    known mechanical reference regardless of motor power."""
    mount_a = EqmodSimMount(state_key="rig3")
    await mount_a.connect()
    await mount_a.park()

    simulate_power_cycle("rig3")

    mount_b = EqmodSimMount(state_key="rig3")
    await mount_b.connect()
    status = await mount_b.get_status()
    assert status.is_synced is True
    assert status.is_parked is True
    assert status.dec == pytest.approx(90.0, abs=1e-6)


# --- Pulse guiding ---

async def test_pulse_guide_moves_by_guide_rate_times_duration(monkeypatch) -> None:
    clock = _fake_clock(monkeypatch)
    mount = EqmodSimMount()
    await mount.connect()
    await mount.unpark()
    await mount.sync(_coord(180.0, 45.0))
    await mount.set_tracking(True)
    await mount.pulse_guide("N", 50)
    status = await mount.get_status()
    expected = 45.0 + 0.5 * simulator._SIDEREAL_DEG_PER_SEC * 0.05
    assert status.dec == pytest.approx(expected, abs=1e-9)
    await mount.disconnect()


async def test_pulse_guide_refused_while_parked() -> None:
    mount = EqmodSimMount()
    await mount.connect()
    with pytest.raises(ValueError, match="parked"):
        await mount.pulse_guide("N", 50)
    await mount.disconnect()
