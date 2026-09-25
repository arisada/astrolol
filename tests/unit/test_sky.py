"""Offline sky maths (astrolol/mount/sky.py), checked against astropy."""
from __future__ import annotations

from datetime import datetime, timezone

import astropy.units as u
import pytest
from astropy.coordinates import SkyCoord

from astrolol.mount.sky import altitude_of, icrs_to_jnow, jnow_to_icrs


def normalize_hours(h: float) -> float:
    return (h + 12.0) % 24.0 - 12.0


def normalize_degrees(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


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
    from astrolol.mount.sky import local_sidereal_time_h

    when = datetime(2020, 3, 15, 21, 30, tzinfo=timezone.utc)
    expected = Time(when).sidereal_time("mean", longitude=2.35 * u.deg).hour
    assert normalize_hours(local_sidereal_time_h(when, 2.35) - expected) == pytest.approx(0.0, abs=1 / 3600)


def test_lst_advances_at_the_sidereal_rate() -> None:
    from datetime import timedelta
    from astrolol.mount.sky import local_sidereal_time_h

    t0 = datetime(2026, 9, 24, 20, 0, tzinfo=timezone.utc)
    delta = local_sidereal_time_h(t0 + timedelta(hours=1), 0) - local_sidereal_time_h(t0, 0)
    assert delta == pytest.approx(1.0027379, abs=1e-6)


@pytest.mark.parametrize("ha,dec", [(-3.0, 20.0), (0.0, 45.0), (2.5, -10.0), (8.0, 70.0)])
def test_alt_az_matches_astropy(ha: float, dec: float) -> None:
    from astropy.coordinates import AltAz, EarthLocation
    from astropy.time import Time
    from astrolol.mount.sky import alt_az

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
    from astrolol.mount.sky import alt_az

    alt, az = alt_az(0.0, 90.0, 48.0)            # the pole sits due north at altitude = latitude
    assert alt == pytest.approx(48.0) and normalize_degrees(az) == pytest.approx(0.0, abs=1e-6)
    alt, az = alt_az(0.0, 0.0, 48.0)             # celestial equator on the meridian is due south
    assert alt == pytest.approx(42.0) and az == pytest.approx(180.0)
    alt, az = alt_az(-6.0, 0.0, 48.0)            # equator at HA -6h rises due east
    assert alt == pytest.approx(0.0, abs=1e-9) and az == pytest.approx(90.0)


def test_altitude_of_matches_the_pole() -> None:
    when = datetime(2026, 9, 24, 22, 0, tzinfo=timezone.utc)
    pole = jnow_to_icrs(0.0, 90.0, when)  # pole of date sits at altitude = latitude
    assert altitude_of(pole, when, 48.85, 2.35) == pytest.approx(48.85, abs=1e-6)
