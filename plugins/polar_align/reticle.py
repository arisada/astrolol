"""Polar-scope reticle math (Part 1 of the plugin -- see SPEC.md section 2). A purely
computed display: no device I/O is needed to show the dot, only the site's lat/lon and
the system clock.

Deliberately decoupled from astrolol.devices/equipment: this module takes plain floats
and datetimes, never an app/request/device handle. plugins/polar_align/api.py owns all
of that plumbing (site lookup), mirroring the solver.py/wizard.py split for Part 2.
"""
from __future__ import annotations

from datetime import datetime

from astropy.coordinates import SkyCoord
from pydantic import BaseModel, Field

from astrolol.mount.sky import icrs_to_jnow, local_sidereal_time_h

# Catalog position (J2000, alpha UMi / HIP 11767). Precessed at render time via
# icrs_to_jnow, not hardcoded as a fixed "current" RA/Dec -- Polaris's RA drifts ~30' of
# RA between J2000 and now, which at this display's ~38' reticle radius is ~7.5deg of
# reticle-angle error (~5' of mis-placement) if left uncorrected. See SPEC.md section 2.
POLARIS_ICRS = SkyCoord(ra="02h31m49.09s", dec="+89d15m50.8s", frame="icrs")


class ReticleState(BaseModel):
    angle_deg: float = Field(
        description="Polaris's current clock position, 0-360deg, 0deg = due south in "
        "Hour Angle, 12 o'clock on the reticle"
    )
    when: datetime


def polaris_raw_angle_deg(when: datetime, latitude_deg: float, longitude_deg: float) -> float:
    """Polaris's current Hour Angle, in degrees, 0-360 (SPEC.md section 2's "reticle
    angle is still fundamentally HA_polaris = LST - RA_polaris" math)."""
    ra_h, _dec_deg = icrs_to_jnow(POLARIS_ICRS, when)
    lst = local_sidereal_time_h(when, longitude_deg)
    return (lst - ra_h) * 15.0 % 360.0


def compute_reticle_state(when: datetime, latitude_deg: float, longitude_deg: float) -> ReticleState:
    """The live reticle reading: where Polaris should sit on the dial right now."""
    return ReticleState(angle_deg=polaris_raw_angle_deg(when, latitude_deg, longitude_deg), when=when)
