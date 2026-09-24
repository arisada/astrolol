"""Tests for the German equatorial mount geometry (pure maths, no hardware)."""
from __future__ import annotations

from datetime import datetime, timezone

import astropy.units as u
import pytest
from astropy.coordinates import SkyCoord

from plugins.eqmod.geometry import (
    AxisAngles,
    MountGeometry,
    PierSide,
    SyncOffset,
    axes_to_ha_dec,
    ha_dec_to_axes,
    icrs_to_jnow,
    jnow_to_icrs,
    normalize_degrees,
    normalize_hours,
    opposite,
    pier_side_for_ha,
)

CPR = 4_608_000


# --- Wrapping ---

@pytest.mark.parametrize("h,expected", [(0, 0), (12, 12), (-12, 12), (13, -11), (-13, 11), (36, 12), (23.5, -0.5)])
def test_normalize_hours(h: float, expected: float) -> None:
    assert normalize_hours(h) == pytest.approx(expected)


@pytest.mark.parametrize("d,expected", [(0, 0), (180, 180), (-180, 180), (190, -170), (-190, 170), (720, 0)])
def test_normalize_degrees(d: float, expected: float) -> None:
    assert normalize_degrees(d) == pytest.approx(expected)


# --- Axis angles <-> HA/Dec ---

def test_home_points_at_the_pole_on_the_6h_circle() -> None:
    ha, dec, side = axes_to_ha_dec(AxisAngles(0.0, 0.0))
    assert dec == pytest.approx(90.0)
    assert ha == pytest.approx(6.0)
    assert side is PierSide.EAST


def test_pure_dec_rotation_from_home_swings_along_the_6h_circle() -> None:
    ha, dec, side = axes_to_ha_dec(AxisAngles(0.0, 90.0))
    assert (ha, dec, side) == (pytest.approx(6.0), pytest.approx(0.0), PierSide.EAST)
    ha, dec, side = axes_to_ha_dec(AxisAngles(0.0, -90.0))
    assert (ha, dec, side) == (pytest.approx(-6.0), pytest.approx(0.0), PierSide.WEST)


@pytest.mark.parametrize("side", list(PierSide))
@pytest.mark.parametrize("ha", [-11.5, -6.0, -0.5, 0.0, 0.5, 6.0, 11.5])
@pytest.mark.parametrize("dec", [-60.0, -10.0, 0.0, 45.0, 89.0])
def test_ha_dec_roundtrip(side: PierSide, ha: float, dec: float) -> None:
    ha2, dec2, side2 = axes_to_ha_dec(ha_dec_to_axes(ha, dec, side))
    assert normalize_hours(ha2 - ha) == pytest.approx(0.0, abs=1e-9)
    assert dec2 == pytest.approx(dec)
    assert side2 is side


def test_the_two_pier_sides_are_the_same_sky_position_via_a_flip() -> None:
    east = ha_dec_to_axes(0.5, 30.0, PierSide.EAST)
    west = ha_dec_to_axes(0.5, 30.0, PierSide.WEST)
    assert normalize_hours(west.ra_axis_h - east.ra_axis_h) == pytest.approx(12.0)
    assert west.dec_axis_deg == pytest.approx(-east.dec_axis_deg)


def test_ha_dec_to_axes_rejects_bad_dec() -> None:
    with pytest.raises(ValueError):
        ha_dec_to_axes(0.0, 91.0, PierSide.EAST)


# --- Pier side policy: counterweight never above horizontal at the target ---

@pytest.mark.parametrize("ha", [-11.9, -6.0, -0.01, 0.0, 0.01, 6.0, 11.9])
def test_chosen_pier_side_keeps_counterweight_down(ha: float) -> None:
    side = pier_side_for_ha(ha)
    assert abs(ha_dec_to_axes(ha, 20.0, side).ra_axis_h) <= 6.0 + 1e-9
    assert side is (PierSide.EAST if ha >= 0 else PierSide.WEST)


def test_opposite() -> None:
    assert opposite(PierSide.EAST) is PierSide.WEST
    assert opposite(PierSide.WEST) is PierSide.EAST


# --- Counts <-> axes ---

@pytest.mark.parametrize("ra_reverse", [False, True])
@pytest.mark.parametrize("dec_reverse", [False, True])
def test_counts_roundtrip(ra_reverse: bool, dec_reverse: bool) -> None:
    g = MountGeometry(CPR, CPR, ra_reverse, dec_reverse, SyncOffset(0.3, -1.2))
    for ra_c, dec_c in [(0, 0), (123_456, -7_890), (-1_000_000, 900_000)]:
        assert g.axes_to_counts(g.counts_to_axes(ra_c, dec_c)) == (ra_c, dec_c)


def test_counts_scale() -> None:
    g = MountGeometry(CPR, CPR)
    axes = g.counts_to_axes(CPR // 4, CPR // 4)
    assert axes.ra_axis_h == pytest.approx(6.0)
    assert axes.dec_axis_deg == pytest.approx(90.0)


def test_reverse_flips_the_sign() -> None:
    assert MountGeometry(CPR, CPR, ra_reverse=True).counts_to_axes(CPR // 4, 0).ra_axis_h == pytest.approx(-6.0)
    assert MountGeometry(CPR, CPR, dec_reverse=True).counts_to_axes(0, CPR // 4).dec_axis_deg == pytest.approx(-90.0)


# --- GOTO targets and pointing ---

@pytest.mark.parametrize("ra,dec", [(5.0, 20.0), (17.25, -15.0), (0.1, 80.0)])
def test_target_counts_then_pointing_roundtrip(ra: float, dec: float) -> None:
    g = MountGeometry(CPR, CPR, offset=SyncOffset(0.1, 0.5))
    lst = 3.0
    ra_c, dec_c, side = g.target_counts(ra, dec, lst)
    ra2, dec2, ha2, side2 = g.pointing(ra_c, dec_c, lst)
    assert normalize_hours(ra2 - ra) == pytest.approx(0.0, abs=1e-5)
    assert dec2 == pytest.approx(dec, abs=1e-4)
    assert side2 is side


def test_target_counts_can_force_a_pier_side() -> None:
    g = MountGeometry(CPR, CPR)
    *_, side = g.target_counts(2.0, 10.0, lst_h=3.0)  # HA +1h: natural side is East
    assert side is PierSide.EAST
    *_, forced = g.target_counts(2.0, 10.0, lst_h=3.0, side=PierSide.WEST)
    assert forced is PierSide.WEST


# --- Sync ---

def test_sync_makes_current_counts_point_exactly_at_the_solved_position() -> None:
    g = MountGeometry(CPR, CPR)
    lst = 10.0
    ra_c, dec_c, _ = g.target_counts(9.0, 30.0, lst)
    g.sync(ra_c, dec_c, 9.2, 31.0, lst)  # plate solve says we're slightly off
    ra, dec, _, _ = g.pointing(ra_c, dec_c, lst)
    assert ra == pytest.approx(9.2, abs=1e-6)
    assert dec == pytest.approx(31.0, abs=1e-6)


@pytest.mark.parametrize("dec_reverse", [False, True])
def test_one_sync_corrects_an_eyeballed_home_on_both_pier_sides(dec_reverse: bool) -> None:
    """The real mount was homed 1.5 deg / 20 min off. Sync once on the west side,
    then GOTO targets on both sides must land exactly (the flip case is the point)."""
    truth = MountGeometry(CPR, CPR, dec_reverse=dec_reverse, offset=SyncOffset(-0.33, 1.5))
    model = MountGeometry(CPR, CPR, dec_reverse=dec_reverse)
    lst = 7.0

    # Aim with the uncorrected model at an eastern star, "plate solve" with the truth, sync.
    ra_c, dec_c, side = model.target_counts(9.0, 25.0, lst)
    assert side is PierSide.WEST
    solved_ra, solved_dec, _, _ = truth.pointing(ra_c, dec_c, lst)
    model.sync(ra_c, dec_c, solved_ra, solved_dec, lst)

    for ra, dec in [(8.5, 40.0), (4.0, 10.0), (2.0, -20.0)]:  # eastern, then western (flip) targets
        ra_c, dec_c, _ = model.target_counts(ra, dec, lst)
        got_ra, got_dec, _, _ = truth.pointing(ra_c, dec_c, lst)
        assert normalize_hours(got_ra - ra) == pytest.approx(0.0, abs=1e-5)
        assert got_dec == pytest.approx(dec, abs=1e-4)


# --- Frames ---

def test_icrs_jnow_roundtrip() -> None:
    when = datetime(2026, 9, 24, 22, 0, tzinfo=timezone.utc)
    coord = SkyCoord(ra=83.82 * u.deg, dec=-5.39 * u.deg, frame="icrs")
    ra_h, dec = icrs_to_jnow(coord, when)
    assert ra_h * 15.0 != pytest.approx(83.82, abs=1e-3)  # precession since J2000 is not negligible
    back = jnow_to_icrs(ra_h, dec, when)
    assert back.separation(coord).arcsec < 0.01


# --- Offline LST and Alt/Az, checked against astropy for a date inside its bundled tables ---

def test_lst_matches_astropy_mean_sidereal_time() -> None:
    from astropy.time import Time
    from plugins.eqmod.geometry import local_sidereal_time_h

    when = datetime(2020, 3, 15, 21, 30, tzinfo=timezone.utc)
    expected = Time(when).sidereal_time("mean", longitude=2.35 * u.deg).hour
    assert normalize_hours(local_sidereal_time_h(when, 2.35) - expected) == pytest.approx(0.0, abs=1 / 3600)


def test_lst_advances_at_the_sidereal_rate() -> None:
    from datetime import timedelta
    from plugins.eqmod.geometry import local_sidereal_time_h

    t0 = datetime(2026, 9, 24, 20, 0, tzinfo=timezone.utc)
    delta = local_sidereal_time_h(t0 + timedelta(hours=1), 0) - local_sidereal_time_h(t0, 0)
    assert delta == pytest.approx(1.0027379, abs=1e-6)


@pytest.mark.parametrize("ha,dec", [(-3.0, 20.0), (0.0, 45.0), (2.5, -10.0), (8.0, 70.0)])
def test_alt_az_matches_astropy(ha: float, dec: float) -> None:
    from astropy.coordinates import AltAz, EarthLocation
    from astropy.time import Time
    from plugins.eqmod.geometry import alt_az

    when = datetime(2020, 3, 15, 21, 30, tzinfo=timezone.utc)
    lat, lon = 48.85, 2.35
    lst = Time(when).sidereal_time("apparent", longitude=lon * u.deg).hour
    # HA is defined in the equinox-of-date frame, so place the star there (ICRS would add ~20y of precession).
    from astropy.coordinates import FK5
    star = SkyCoord(ra=((lst - ha) % 24) * u.hourangle, dec=dec * u.deg, frame=FK5(equinox=Time(when)))
    ref = star.transform_to(AltAz(obstime=Time(when), location=EarthLocation(lat=lat * u.deg, lon=lon * u.deg)))
    alt, az = alt_az(ha, dec, lat)
    # Residual is nutation + aberration (tens of arcsec); no refraction on either side.
    assert alt == pytest.approx(ref.alt.deg, abs=0.02)
    assert normalize_degrees(az - ref.az.deg) == pytest.approx(0.0, abs=0.05)


def test_alt_az_cardinal_points() -> None:
    from plugins.eqmod.geometry import alt_az

    alt, az = alt_az(0.0, 90.0, 48.0)            # the pole sits due north at altitude = latitude
    assert alt == pytest.approx(48.0) and normalize_degrees(az) == pytest.approx(0.0, abs=1e-6)
    alt, az = alt_az(0.0, 0.0, 48.0)             # celestial equator on the meridian is due south
    assert alt == pytest.approx(42.0) and az == pytest.approx(180.0)
    alt, az = alt_az(-6.0, 0.0, 48.0)            # equator at HA -6h rises due east
    assert alt == pytest.approx(0.0, abs=1e-9) and az == pytest.approx(90.0)
