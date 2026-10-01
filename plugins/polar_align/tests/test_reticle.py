"""Tests for the polar-scope reticle math (Part 1). What's tested independently here is
specifically the Hour Angle formula (via astropy's own sidereal-time computation, a
different code path than sky.py's hand-rolled GMST polynomial) -- the precession
(icrs_to_jnow) and sidereal-time (local_sidereal_time_h) pieces it's built on are
astrolol.mount.sky's own, already covered by test_solver.py's extensive independent-
oracle testing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import astropy.units as u
import pytest
from astropy.time import Time

from astrolol.mount.sky import icrs_to_jnow
from plugins.polar_align.reticle import POLARIS_ICRS, compute_reticle_state, polaris_raw_angle_deg

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
# compute_reticle_state
# ===========================================================================


def test_compute_reticle_state_matches_raw_angle() -> None:
    state = compute_reticle_state(WHEN, LATITUDE, LONGITUDE)
    assert state.angle_deg == pytest.approx(polaris_raw_angle_deg(WHEN, LATITUDE, LONGITUDE))
    assert state.when == WHEN
