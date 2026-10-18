"""Solar system object positions via Astropy — fully offline."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import astropy.units as u
from astropy.coordinates import EarthLocation, get_body
from astropy.time import Time

# Observer site: (latitude deg, longitude deg east, altitude m).
Site = tuple[float, float, float]

# Keys are what astropy's get_body() understands; values are display names.
_BODIES: dict[str, str] = {
    "sun": "Sun",
    "moon": "Moon",
    "mercury": "Mercury",
    "venus": "Venus",
    "mars": "Mars",
    "jupiter": "Jupiter",
    "saturn": "Saturn",
    "uranus": "Uranus",
    "neptune": "Neptune",
}


def _ra_dec(body_key: str, when: datetime, site: Site | None = None) -> tuple[float, float]:
    # Direction in GCRS axes (= ICRS axes), seen from the site, or from the Earth's centre
    # without one (the Moon differs by up to ~1°: parallax). Do NOT convert to ICRS: for a body
    # with a distance that gives the direction seen from the solar-system barycentre, which for
    # the Moon is up to ~100° away from where it is in our sky.
    location = (
        EarthLocation.from_geodetic(lon=site[1] * u.deg, lat=site[0] * u.deg, height=site[2] * u.m)
        if site is not None else None
    )
    coord = get_body(body_key, Time(when), location=location)
    return float(coord.ra.deg), float(coord.dec.deg)


def _angular_sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    ra1r, dec1r, ra2r, dec2r = map(math.radians, (ra1, dec1, ra2, dec2))
    dra = ra2r - ra1r
    ddec = dec2r - dec1r
    a = (
        math.sin(ddec / 2) ** 2
        + math.cos(dec1r) * math.cos(dec2r) * math.sin(dra / 2) ** 2
    )
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def search(query: str, when: datetime | None = None, site: Site | None = None) -> list[dict[str, Any]]:
    """Return solar system bodies whose name contains *query* (case-insensitive), as seen from *site*."""
    t = when or _now()
    q = query.lower().strip()
    results = []
    for key, display in _BODIES.items():
        if q in key or q in display.lower():
            ra, dec = _ra_dec(key, t, site)
            results.append(
                {
                    "name": display,
                    "aliases": [],
                    "type": "Solar System",
                    "ra": ra,
                    "dec": dec,
                    "source": "solar_system",
                }
            )
    return results


def cone_search(
    ra: float, dec: float, radius_arcmin: float, when: datetime | None = None,
    site: Site | None = None,
) -> list[dict[str, Any]]:
    """Return solar system bodies within *radius_arcmin* of (ra, dec)."""
    t = when or _now()
    results = []
    for key, display in _BODIES.items():
        bra, bdec = _ra_dec(key, t, site)
        sep = _angular_sep_deg(ra, dec, bra, bdec) * 60.0
        if sep <= radius_arcmin:
            results.append(
                {
                    "name": display,
                    "aliases": [],
                    "type": "Solar System",
                    "ra": bra,
                    "dec": bdec,
                    "source": "solar_system",
                    "distance_arcmin": round(sep, 3),
                }
            )
    results.sort(key=lambda x: x["distance_arcmin"])
    return results
