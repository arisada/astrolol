"""Polar-scope reticle math (Part 1 of the plugin -- see SPEC.md section 2). A purely
computed display: no device I/O is needed to show the dot, only the site's lat/lon and
the system clock. A connected mount is useful for two optional things -- the "RA axis at
home" validity check, and skipping a manual HA entry during calibration -- not required
for either.

Deliberately decoupled from astrolol.devices/equipment: this module takes plain floats
and datetimes, never an app/request/device handle. plugins/polar_align/api.py owns all
of that plumbing (site lookup, mount status reads, settings persistence), mirroring the
solver.py/wizard.py split for Part 2.
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

# How far the RA axis's reported Hour Angle may drift from its calibrated value before
# the displayed dot is flagged as unreliable. The reticle is physically fixed to the RA
# axis, so any drift here means the *whole* calibration (not just precision) is off --
# this isn't a tolerance for sky-position error, it's "has the axis moved at all" with
# slack for encoder/reporting noise, hence the fairly tight default.
_HOME_TOLERANCE_DEG = 2.0


class ReticleCalibration(BaseModel):
    """The physical relationship between one mount's polar scope reticle and the sky,
    captured once by the user (SPEC.md section 2, "Calibration"): rotate the RA axis by
    hand until the reticle's 0deg/12-o'clock mark is plumb vertical, then call calibrate()
    at that instant. Keyed by the equipment-store mount node in plugin_settings, not a
    runtime device id, so it survives reconnects and works even with no mount connected.
    """

    offset_deg: float = Field(
        description="Added to the raw sky angle to get the reticle's displayed angle; "
        "derived purely from time+location at calibration time, not from any mount reading"
    )
    home_ha_hours: float | None = Field(
        default=None,
        description="The mount's own reported Hour Angle at calibration time, if a mount "
        "was connected then -- enables the live axis_at_home check. None if calibrated "
        "with no mount connected; the dot still displays, just without that check.",
    )
    calibrated_at: datetime


class ReticleState(BaseModel):
    angle_deg: float = Field(
        description="Polaris's current clock position on the reticle, 0-360deg, measured "
        "from the calibrated 0deg/12-o'clock mark (or the raw uncalibrated sky angle, "
        "0deg = due south in Hour Angle, if calibrated is False)"
    )
    radius_arcmin: float = Field(description="Polaris's current angular distance from the true celestial pole")
    calibrated: bool
    axis_at_home: bool | None = Field(
        description="None if unverifiable (no calibration-time mount reading, or no mount "
        "connected now); otherwise whether the RA axis's current HA still matches the "
        "calibration. False means angle_deg is likely wrong, not just imprecise -- the "
        "whole reticle physically rotates with the axis."
    )
    when: datetime


def polaris_raw_angle_deg(when: datetime, latitude_deg: float, longitude_deg: float) -> float:
    """The uncalibrated sky angle: Polaris's current Hour Angle, in degrees, 0-360 (SPEC.md
    section 2's "reticle angle is still fundamentally HA_polaris = LST - RA_polaris" math).
    """
    ra_h, _dec_deg = icrs_to_jnow(POLARIS_ICRS, when)
    lst = local_sidereal_time_h(when, longitude_deg)
    return (lst - ra_h) * 15.0 % 360.0


def polaris_radius_arcmin(when: datetime) -> float:
    """Polaris's current angular distance from the true (northern) celestial pole, in
    arcminutes. Northern-hemisphere math only -- callers must gate on latitude_deg >= 0
    themselves (SPEC.md section 6 decision 4); this function doesn't know the observer's
    site, only the date, so it can't enforce that gate itself."""
    _ra_h, dec_deg = icrs_to_jnow(POLARIS_ICRS, when)
    return (90.0 - dec_deg) * 60.0


def calibrate(
    when: datetime,
    latitude_deg: float,
    longitude_deg: float,
    mount_ha_hours: float | None,
) -> ReticleCalibration:
    """Call at the instant the user has rotated the RA axis until the reticle's 0deg mark
    is plumb-vertical. offset_deg is computed purely from time+location, so this works
    with no mount connected; mount_ha_hours (the mount's own reported HA right now, if
    one is connected) is stored as-is, for the later axis_at_home check only -- it plays
    no part in computing offset_deg itself."""
    raw = polaris_raw_angle_deg(when, latitude_deg, longitude_deg)
    return ReticleCalibration(offset_deg=(-raw) % 360.0, home_ha_hours=mount_ha_hours, calibrated_at=when)


def compute_reticle_state(
    when: datetime,
    latitude_deg: float,
    longitude_deg: float,
    calibration: ReticleCalibration | None,
    mount_ha_hours: float | None,
) -> ReticleState:
    """The live reticle reading. calibration=None shows the raw (uncalibrated) sky angle
    rather than refusing to show anything -- still useful context while the user hasn't
    calibrated yet. mount_ha_hours is the mount's own current reported Hour Angle, used
    only for the axis_at_home check; omit it (None) if no mount is connected."""
    raw = polaris_raw_angle_deg(when, latitude_deg, longitude_deg)
    offset = calibration.offset_deg if calibration is not None else 0.0
    angle_deg = (raw + offset) % 360.0

    axis_at_home: bool | None = None
    if calibration is not None and calibration.home_ha_hours is not None and mount_ha_hours is not None:
        drift_h = (mount_ha_hours - calibration.home_ha_hours + 12.0) % 24.0 - 12.0
        axis_at_home = abs(drift_h * 15.0) <= _HOME_TOLERANCE_DEG

    return ReticleState(
        angle_deg=angle_deg,
        radius_arcmin=polaris_radius_arcmin(when),
        calibrated=calibration is not None,
        axis_at_home=axis_at_home,
        when=when,
    )
