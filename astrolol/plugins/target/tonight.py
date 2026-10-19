"""What is well placed tonight: the dark hours, and how high each object gets in them.

Altitudes come from the sidereal time and the usual spherical formula (not a full astropy
transform per object), which keeps a few hundred objects cheap on a small computer; precession
and refraction are ignored, a fraction of a degree.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, get_body, get_sun
from astropy.time import Time

from astrolol.plugins.target.models import TonightItem, TonightResult

STEP_MINUTES = 10
LOOKAHEAD_HOURS = 26
# The Sun must be this far below the horizon for the sky to count as dark: nautical twilight like
# the imaging window of the altitude graph, civil where the nights are too short for that.
DARK_SUN_ALTITUDES = (-12.0, -6.0)

MOON_CLOSE_DEG = 30.0       # nearer than this to the Moon is "too close"…
MOON_MIN_ILLUMINATION = 0.15    # …unless it is a thin crescent


@dataclass(frozen=True)
class Window:
    """The coming dark hours, sampled every STEP_MINUTES."""
    times: Time

    @property
    def start(self) -> datetime:
        return self.times[0].to_datetime(timezone.utc)

    @property
    def end(self) -> datetime:
        return self.times[-1].to_datetime(timezone.utc)

    @property
    def middle(self) -> datetime:
        return self.times[len(self.times) // 2].to_datetime(timezone.utc)


def find_dark_window(now: datetime, latitude: float, longitude: float, altitude_m: float) -> Window | None:
    """The current or next dark period starting from *now*, or None when the Sun never gets low enough."""
    location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=altitude_m * u.m)
    steps = LOOKAHEAD_HOURS * 60 // STEP_MINUTES + 1
    times = Time(now) + np.arange(steps) * STEP_MINUTES * u.min
    sun_alt = get_sun(times).transform_to(AltAz(obstime=times, location=location)).alt.deg
    for threshold in DARK_SUN_ALTITUDES:
        dark = sun_alt < threshold
        if not dark.any():
            continue
        first = int(np.argmax(dark))
        after = np.nonzero(~dark[first:])[0]
        last = first + int(after[0]) - 1 if after.size else len(dark) - 1
        return Window(times[first:last + 1])
    return None


def altitudes(ra_deg: np.ndarray, dec_deg: np.ndarray, lst_deg: np.ndarray, latitude: float) -> np.ndarray:
    """Altitudes in degrees, shape (objects, times)."""
    lat = math.radians(latitude)
    dec = np.radians(dec_deg)[:, None]
    hour_angle = np.radians(lst_deg[None, :] - ra_deg[:, None])
    sin_alt = math.sin(lat) * np.sin(dec) + math.cos(lat) * np.cos(dec) * np.cos(hour_angle)
    return np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))


def separation_deg(ra1: np.ndarray, dec1: np.ndarray, ra2: float, dec2: float) -> np.ndarray:
    """Great-circle separation of each (ra1, dec1) from the point (ra2, dec2), in degrees."""
    r1, d1, r2, d2 = np.radians(ra1), np.radians(dec1), math.radians(ra2), math.radians(dec2)
    a = np.sin((d2 - d1) / 2) ** 2 + np.cos(d1) * math.cos(d2) * np.sin((r2 - r1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.minimum(1.0, np.sqrt(a))))


def is_too_close_to_moon(separation: float, moon_altitude: float, illumination: float) -> bool:
    """A bright Moon that is up and near the object spoils it."""
    return moon_altitude > 0.0 and illumination >= MOON_MIN_ILLUMINATION and separation < MOON_CLOSE_DEG


def rank(items: list[TonightItem]) -> list[TonightItem]:
    """Highest first; the objects too close to the Moon after all the others."""
    return sorted(items, key=lambda i: (i.near_moon, -i.alt_now))


def _iso(t: Time) -> str:
    return t.to_datetime(timezone.utc).isoformat()


def compute_tonight(
    candidates: list[dict[str, Any]],
    window: Window,
    latitude: float,
    longitude: float,
    altitude_m: float,
    min_altitude_deg: float = 30.0,
    limit: int = 100,
) -> TonightResult:
    """Rank *candidates* (dicts with name, ra, dec, …) by how high they are at the start of *window*.

    Only objects that reach *min_altitude_deg* during the window are listed."""
    from astroplan import moon_illumination

    result = TonightResult(
        window_start=_iso(window.times[0]), window_end=_iso(window.times[-1]),
        min_altitude_deg=min_altitude_deg,
    )
    if not candidates:
        return result

    times = window.times
    middle = times[len(times) // 2]
    location = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=altitude_m * u.m)
    lst = np.asarray(times.sidereal_time("mean", longitude=longitude * u.deg).deg)
    ra = np.array([c["ra"] for c in candidates], dtype=float)
    dec = np.array([c["dec"] for c in candidates], dtype=float)
    alts = altitudes(ra, dec, lst, latitude)

    moon = get_body("moon", middle, location=location)
    illumination = float(moon_illumination(middle))
    result.moon_illumination = round(illumination, 3)
    moon_alts = altitudes(np.array([moon.ra.deg]), np.array([moon.dec.deg]), lst, latitude)[0]
    moon_sep = separation_deg(ra, dec, float(moon.ra.deg), float(moon.dec.deg))

    items: list[TonightItem] = []
    for k, cand in enumerate(candidates):
        row = alts[k]
        above = row >= min_altitude_deg
        if not above.any():
            continue
        peak = int(np.argmax(row))
        rise = None if above[0] else _iso(times[int(np.argmax(above))])
        last_above = len(above) - 1 - int(np.argmax(above[::-1]))
        set_ = None if last_above == len(above) - 1 else _iso(times[last_above])
        is_moon = cand.get("source") == "solar_system" and cand.get("name") == "Moon"
        items.append(TonightItem(
            name=cand["name"], aliases=cand.get("aliases", []), type=cand.get("type", ""),
            ra=cand["ra"], dec=cand["dec"], source=cand.get("source", "catalog"),
            mag=cand.get("mag"), size_arcmin=cand.get("size_arcmin"),
            alt_now=round(float(row[0]), 1), peak_alt=round(float(row[peak]), 1), peak_time=_iso(times[peak]),
            rise_time=rise, set_time=set_,
            moon_separation=None if is_moon else round(float(moon_sep[k]), 1),
            near_moon=False if is_moon else is_too_close_to_moon(
                float(moon_sep[k]), float(moon_alts[peak]), illumination),
        ))
    result.items = rank(items)[:limit]
    return result


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
