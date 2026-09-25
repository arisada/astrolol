"""German equatorial mount geometry: motor counts <-> axis angles <-> HA/Dec <-> RA/Dec.

Northern hemisphere, polar home at power-on (counts 0 = counterweights down, OTA on
the pole). Axis angles are measured from home:
- A: RA axis, hours, positive in the tracking (westward) direction.
- D: Dec axis, degrees. The counterweight shaft is coaxial with the Dec axis, so at
  home the Dec axis lies in the meridian plane and a pure Dec rotation swings the OTA
  along the 6h/18h hour circle.
Pier side follows the "which side of the pier the OTA is on" convention:
- D >= 0: OTA east of the pier, looking west: Dec = 90 - D, HA = A + 6h.
- D <  0: OTA west of the pier, looking east: Dec = 90 + D, HA = A - 6h.
Sync is a single offset in axis-angle space, so it corrects home/zero-point error the
same way on both pier sides.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum



class PierSide(StrEnum):
    EAST = "East"
    WEST = "West"


def normalize_hours(h: float) -> float:
    """Wrap to (-12, 12]."""
    h = math.fmod(h, 24.0)
    if h > 12.0:
        h -= 24.0
    elif h <= -12.0:
        h += 24.0
    return h


def normalize_degrees(d: float) -> float:
    """Wrap to (-180, 180]."""
    d = math.fmod(d, 360.0)
    if d > 180.0:
        d -= 360.0
    elif d <= -180.0:
        d += 360.0
    return d


@dataclass(frozen=True)
class AxisAngles:
    ra_axis_h: float
    dec_axis_deg: float


def pier_side_of(dec_axis_deg: float) -> PierSide:
    return PierSide.EAST if normalize_degrees(dec_axis_deg) >= 0 else PierSide.WEST


def axes_to_ha_dec(axes: AxisAngles) -> tuple[float, float, PierSide]:
    """Return (hour angle h, declination deg, pier side)."""
    d = normalize_degrees(axes.dec_axis_deg)
    side = pier_side_of(d)
    if side is PierSide.EAST:
        return normalize_hours(axes.ra_axis_h + 6.0), 90.0 - d, side
    return normalize_hours(axes.ra_axis_h - 6.0), 90.0 + d, side


def ha_dec_to_axes(ha_h: float, dec_deg: float, side: PierSide) -> AxisAngles:
    if not -90.0 <= dec_deg <= 90.0:
        raise ValueError(f"Declination out of range: {dec_deg}")
    if side is PierSide.EAST:
        return AxisAngles(normalize_hours(ha_h - 6.0), 90.0 - dec_deg)
    return AxisAngles(normalize_hours(ha_h + 6.0), dec_deg - 90.0)


def pier_side_for_ha(ha_h: float) -> PierSide:
    """Side that keeps the counterweight at/below horizontal: west targets -> OTA east."""
    return PierSide.EAST if normalize_hours(ha_h) >= 0 else PierSide.WEST


def opposite(side: PierSide) -> PierSide:
    return PierSide.WEST if side is PierSide.EAST else PierSide.EAST


# --- Counts <-> axis angles for a specific mount ---

@dataclass
class SyncOffset:
    ra_axis_h: float = 0.0
    dec_axis_deg: float = 0.0


@dataclass
class MountGeometry:
    """Per-mount conversion, holding CPR, calibrated direction signs and the sync offset."""

    ra_cpr: int
    dec_cpr: int
    ra_reverse: bool = False
    dec_reverse: bool = False
    offset: SyncOffset | None = None

    def counts_to_axes(self, ra_counts: int, dec_counts: int) -> AxisAngles:
        off = self.offset or SyncOffset()
        ra_sign = -1 if self.ra_reverse else 1
        dec_sign = -1 if self.dec_reverse else 1
        return AxisAngles(
            normalize_hours(ra_sign * ra_counts * 24.0 / self.ra_cpr + off.ra_axis_h),
            normalize_degrees(dec_sign * dec_counts * 360.0 / self.dec_cpr + off.dec_axis_deg),
        )

    def mechanical_ra_axis_h(self, ra_counts: int) -> float:
        """RA axis angle from counts alone (no sync offset): where the counterweight physically is.

        |angle| = 6h means counterweight horizontal; beyond that it rises.
        """
        ra_sign = -1 if self.ra_reverse else 1
        return normalize_hours(ra_sign * ra_counts * 24.0 / self.ra_cpr)

    def axes_to_counts(self, axes: AxisAngles) -> tuple[int, int]:
        off = self.offset or SyncOffset()
        ra_sign = -1 if self.ra_reverse else 1
        dec_sign = -1 if self.dec_reverse else 1
        ra_mech = normalize_hours(axes.ra_axis_h - off.ra_axis_h)
        dec_mech = normalize_degrees(axes.dec_axis_deg - off.dec_axis_deg)
        return (
            round(ra_sign * ra_mech * self.ra_cpr / 24.0),
            round(dec_sign * dec_mech * self.dec_cpr / 360.0),
        )

    def pointing(self, ra_counts: int, dec_counts: int, lst_h: float) -> tuple[float, float, float, PierSide]:
        """Return (JNow RA h, Dec deg, HA h, pier side) for the given counts."""
        ha, dec, side = axes_to_ha_dec(self.counts_to_axes(ra_counts, dec_counts))
        return (lst_h - ha) % 24.0, dec, ha, side

    def target_counts(
        self, ra_jnow_h: float, dec_deg: float, lst_h: float, side: PierSide | None = None
    ) -> tuple[int, int, PierSide]:
        ha = normalize_hours(lst_h - ra_jnow_h)
        side = side or pier_side_for_ha(ha)
        ra_c, dec_c = self.axes_to_counts(ha_dec_to_axes(ha, dec_deg, side))
        return ra_c, dec_c, side

    def sync(self, ra_counts: int, dec_counts: int, ra_jnow_h: float, dec_deg: float, lst_h: float) -> SyncOffset:
        """Make the given counts point at (RA, Dec) on the current pier side; returns the new offset."""
        side = pier_side_of(self.counts_to_axes(ra_counts, dec_counts).dec_axis_deg)
        wanted = ha_dec_to_axes(normalize_hours(lst_h - ra_jnow_h), dec_deg, side)
        mech = MountGeometry(self.ra_cpr, self.dec_cpr, self.ra_reverse, self.dec_reverse).counts_to_axes(
            ra_counts, dec_counts
        )
        self.offset = SyncOffset(
            normalize_hours(wanted.ra_axis_h - mech.ra_axis_h),
            normalize_degrees(wanted.dec_axis_deg - mech.dec_axis_deg),
        )
        return self.offset
