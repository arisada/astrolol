"""Sky maths that must work offline in the field: no IERS tables (LST uses UTC, Alt/Az has
no refraction). ICRS<->JNow uses astropy FK5, which is precession only and needs no IERS.
"""
from __future__ import annotations

import math
from datetime import datetime

import astropy.units as u
from astropy.coordinates import FK5, SkyCoord
from astropy.time import Time


def local_sidereal_time_h(when: datetime, longitude_deg: float) -> float:
    """Mean LST from the GMST formula on UTC; UT1-UTC (<0.9s) is ignored."""
    days_since_j2000 = when.timestamp() / 86400.0 + 2440587.5 - 2451545.0
    gmst = 18.697374558 + 24.06570982441908 * days_since_j2000
    return (gmst + longitude_deg / 15.0) % 24.0


def alt_az(ha_h: float, dec_deg: float, latitude_deg: float) -> tuple[float, float]:
    """Geometric altitude and azimuth (degrees, azimuth from north through east); no refraction."""
    ha, dec, lat = math.radians(ha_h * 15.0), math.radians(dec_deg), math.radians(latitude_deg)
    alt = math.asin(max(-1.0, min(1.0, math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha))))
    az = math.atan2(-math.cos(dec) * math.sin(ha), math.sin(dec) * math.cos(lat) - math.cos(dec) * math.sin(lat) * math.cos(ha))
    return math.degrees(alt), math.degrees(az) % 360.0


def icrs_to_jnow(coord: SkyCoord, when: datetime) -> tuple[float, float]:
    """Return (RA hours, Dec deg) in the equinox-of-date frame."""
    jnow = coord.icrs.transform_to(FK5(equinox=Time(when)))
    return float(jnow.ra.hour), float(jnow.dec.deg)


def jnow_to_icrs(ra_h: float, dec_deg: float, when: datetime) -> SkyCoord:
    return SkyCoord(ra=ra_h * u.hourangle, dec=dec_deg * u.deg, frame=FK5(equinox=Time(when))).icrs


def altitude_of(coord: SkyCoord, when: datetime, latitude_deg: float, longitude_deg: float) -> float:
    """Geometric altitude (degrees) of an ICRS position for an observer at the given site."""
    ra_h, dec = icrs_to_jnow(coord, when)
    ha = local_sidereal_time_h(when, longitude_deg) - ra_h
    return alt_az(ha, dec, latitude_deg)[0]
