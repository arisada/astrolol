"""Tests for the polar-scope reticle math (Part 1). The interesting new logic here is
thin -- a Hour Angle formula and some calibration/offset arithmetic -- since the
precession (icrs_to_jnow) and sidereal-time (local_sidereal_time_h) pieces it's built on
are astrolol.mount.sky's own, already covered by test_solver.py's extensive independent-
oracle testing. What's tested independently here is specifically the formula that
combines them (via astropy's own sidereal-time computation, a different code path than
sky.py's hand-rolled GMST polynomial) and the calibration/home-check arithmetic that's
unique to this module.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import astropy.units as u
import pytest
from astropy.time import Time

from astrolol.mount.sky import icrs_to_jnow
from plugins.polar_align.reticle import (
    POLARIS_ICRS,
    ReticleCalibration,
    calibrate,
    compute_reticle_state,
    polaris_radius_arcmin,
    polaris_raw_angle_deg,
)

LATITUDE = 48.0
LONGITUDE = 11.0
WHEN = datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# polaris_raw_angle_deg -- independent oracle via astropy's own sidereal time
# ===========================================================================


def _oracle_raw_angle_deg(when: datetime, latitude_deg: float, longitude_deg: float) -> float:
    ra_h, _dec_deg = icrs_to_jnow(POLARIS_ICRS, when)
    lst_h = Time(when).sidereal_time("mean", longitude=longitude_deg * u.deg).hour
    return (lst_h - ra_h) * 15.0 % 360.0


@pytest.mark.parametrize(
    "when,latitude_deg,longitude_deg",
    [
        (datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc), 48.0, 11.0),
        (datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc), 40.0, -74.0),
        (datetime(2026, 9, 21, 18, 30, 0, tzinfo=timezone.utc), 51.5, 0.0),
        (datetime(2026, 3, 3, 6, 0, 0, tzinfo=timezone.utc), 35.0, 139.0),
    ],
)
def test_polaris_raw_angle_deg_matches_independent_oracle(when, latitude_deg, longitude_deg) -> None:
    got = polaris_raw_angle_deg(when, latitude_deg, longitude_deg)
    want = _oracle_raw_angle_deg(when, latitude_deg, longitude_deg)
    # Mean vs. mean sidereal time from two different formulas; sub-arcsecond agreement
    # expected, generous tolerance to avoid flakiness from the approximation itself.
    assert got == pytest.approx(want, abs=0.01)


def test_polaris_raw_angle_deg_is_latitude_independent() -> None:
    """Hour Angle depends on longitude and time, not the observer's latitude."""
    a = polaris_raw_angle_deg(WHEN, 10.0, LONGITUDE)
    b = polaris_raw_angle_deg(WHEN, 70.0, LONGITUDE)
    assert a == pytest.approx(b, abs=1e-9)


def test_polaris_raw_angle_deg_advances_with_sidereal_time() -> None:
    """One sidereal day later (not quite 24h) the angle returns to the same value; a
    half (sidereal) day later it's flipped by ~180deg."""
    half_sidereal_day = timedelta(hours=11.967)
    later = WHEN + half_sidereal_day
    a = polaris_raw_angle_deg(WHEN, LATITUDE, LONGITUDE)
    b = polaris_raw_angle_deg(later, LATITUDE, LONGITUDE)
    assert (b - a) % 360.0 == pytest.approx(180.0, abs=0.5)


# ===========================================================================
# polaris_radius_arcmin
# ===========================================================================


def test_polaris_radius_arcmin_is_plausible_for_current_epoch() -> None:
    # Catalog value is ~44' at J2000, currently ~38' and shrinking (SPEC.md section 2).
    r = polaris_radius_arcmin(WHEN)
    assert 35.0 < r < 42.0


def test_polaris_radius_arcmin_matches_dec_formula() -> None:
    _ra_h, dec_deg = icrs_to_jnow(POLARIS_ICRS, WHEN)
    assert polaris_radius_arcmin(WHEN) == pytest.approx((90.0 - dec_deg) * 60.0)


# ===========================================================================
# calibrate() / compute_reticle_state()
# ===========================================================================


def test_calibrate_then_immediate_state_is_zero_angle() -> None:
    calibration = calibrate(WHEN, LATITUDE, LONGITUDE, mount_ha_hours=None)
    state = compute_reticle_state(WHEN, LATITUDE, LONGITUDE, calibration, mount_ha_hours=None)
    assert state.angle_deg == pytest.approx(0.0, abs=1e-6) or state.angle_deg == pytest.approx(360.0, abs=1e-6)
    assert state.calibrated is True


def test_state_advances_by_raw_angle_delta_after_calibration() -> None:
    calibration = calibrate(WHEN, LATITUDE, LONGITUDE, mount_ha_hours=None)
    later = WHEN + timedelta(hours=2)
    state = compute_reticle_state(later, LATITUDE, LONGITUDE, calibration, mount_ha_hours=None)

    raw_at_cal = polaris_raw_angle_deg(WHEN, LATITUDE, LONGITUDE)
    raw_later = polaris_raw_angle_deg(later, LATITUDE, LONGITUDE)
    expected = (raw_later - raw_at_cal) % 360.0
    assert state.angle_deg == pytest.approx(expected, abs=1e-6)


def test_uncalibrated_state_shows_raw_angle() -> None:
    state = compute_reticle_state(WHEN, LATITUDE, LONGITUDE, calibration=None, mount_ha_hours=None)
    assert state.calibrated is False
    assert state.angle_deg == pytest.approx(polaris_raw_angle_deg(WHEN, LATITUDE, LONGITUDE))
    assert state.axis_at_home is None


def test_axis_at_home_none_without_calibration_mount_reading() -> None:
    calibration = calibrate(WHEN, LATITUDE, LONGITUDE, mount_ha_hours=None)  # no mount at calibration time
    state = compute_reticle_state(WHEN, LATITUDE, LONGITUDE, calibration, mount_ha_hours=3.0)
    assert state.axis_at_home is None  # nothing to compare the live reading against


def test_axis_at_home_none_without_live_mount_reading() -> None:
    calibration = calibrate(WHEN, LATITUDE, LONGITUDE, mount_ha_hours=5.0)
    state = compute_reticle_state(WHEN, LATITUDE, LONGITUDE, calibration, mount_ha_hours=None)  # no mount now
    assert state.axis_at_home is None


def test_axis_at_home_true_within_tolerance() -> None:
    calibration = calibrate(WHEN, LATITUDE, LONGITUDE, mount_ha_hours=5.0)
    state = compute_reticle_state(WHEN, LATITUDE, LONGITUDE, calibration, mount_ha_hours=5.05)  # 0.75deg of HA
    assert state.axis_at_home is True


def test_axis_at_home_false_outside_tolerance() -> None:
    calibration = calibrate(WHEN, LATITUDE, LONGITUDE, mount_ha_hours=5.0)
    state = compute_reticle_state(WHEN, LATITUDE, LONGITUDE, calibration, mount_ha_hours=5.5)  # 7.5deg of HA
    assert state.axis_at_home is False


def test_axis_at_home_wraps_correctly_across_the_0_24h_boundary() -> None:
    """home_ha_hours=23.95 and a live reading of 0.05h differ by only 0.1h (1.5deg), not
    ~23.9h -- the comparison must wrap, not do a naive subtraction."""
    calibration = calibrate(WHEN, LATITUDE, LONGITUDE, mount_ha_hours=23.95)
    state = compute_reticle_state(WHEN, LATITUDE, LONGITUDE, calibration, mount_ha_hours=0.05)
    assert state.axis_at_home is True


def test_calibration_round_trips_through_model_dump() -> None:
    """Calibration is persisted as a plain dict (plugin_settings), so it must survive a
    model_dump()/model_validate() round trip, including the datetime field."""
    calibration = calibrate(WHEN, LATITUDE, LONGITUDE, mount_ha_hours=5.0)
    restored = ReticleCalibration.model_validate(calibration.model_dump(mode="json"))
    assert restored == calibration
