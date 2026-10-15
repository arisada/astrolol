"""From a star's position in the image to the polar-axis error, and back to where the star
has to go.

Pure geometry for the live star view. The plate solve of the frame the view starts from gives
the sky position of a reference pixel and the CD matrix (sky degrees per pixel). A star is
fixed on the sky, so when it moves by d pixels in the image the telescope has moved by
-CD @ d on the sky: that gives the same "solved" pointing a recheck would, without solving.
Everything here works in *unbinned sensor pixels*; callers convert from and to binned ones.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from astrolol.plugins.polar_align.solver import (
    _earth_to_altaz,
    _earth_vector,
    correction_displacements,
)
from astrolol.mount.sky import local_sidereal_time_h

Cd = tuple[float, float, float, float]


def _matrix(cd: Cd, binning: float = 1.0) -> np.ndarray:
    """Degrees per *unbinned* pixel, from degrees per pixel of an image binned *binning* x."""
    return np.array([[cd[0], cd[1]], [cd[2], cd[3]]]) / binning


def pointing_after_star_shift(
    ra_hours: float, dec_deg: float, cd: Cd, dx: float, dy: float
) -> tuple[float, float]:
    """The reference pixel's sky position once a star has moved by (dx, dy) unbinned pixels.

    *cd* is for unbinned pixels. Small shifts only (a tangent-plane step).
    """
    xi, eta = _matrix(cd) @ np.array([dx, dy])
    dec = dec_deg - eta
    ra = ra_hours - xi / max(math.cos(math.radians(dec_deg)), 1e-6) / 15.0
    return ra % 24.0, dec


@dataclass(frozen=True)
class StarMoves:
    """Where the star has to go, as unbinned-pixel displacements from where it is now."""

    az: tuple[float, float]  # the azimuth knob's share
    alt: tuple[float, float]  # the altitude knob's share, after the azimuth one

    @property
    def total(self) -> tuple[float, float]:
        return self.az[0] + self.alt[0], self.az[1] + self.alt[1]


def star_moves(
    alt_error_arcmin: float,
    az_error_arcmin: float,
    ra_hours: float,
    dec_deg: float,
    when: datetime,
    latitude_deg: float,
    longitude_deg: float,
    cd: Cd,
) -> StarMoves:
    """Where a star in the image goes when the knobs remove the remaining error.

    (ra_hours, dec_deg) is where the telescope points now (JNow).
    """
    pointing = _earth_vector(ra_hours, dec_deg, when, longitude_deg)
    d_az, d_alt = correction_displacements(alt_error_arcmin, az_error_arcmin, pointing, latitude_deg)

    alpha = math.radians((ra_hours - local_sidereal_time_h(when, longitude_deg)) * 15.0)
    delta = math.radians(dec_deg)
    # Celestial east and north at the pointing, in the same (east, north, up) frame as the displacements.
    east = _earth_to_altaz(np.array([-math.sin(alpha), math.cos(alpha), 0.0]), latitude_deg)
    north = _earth_to_altaz(
        np.array([-math.sin(delta) * math.cos(alpha), -math.sin(delta) * math.sin(alpha), math.cos(delta)]),
        latitude_deg,
    )
    inverse = np.linalg.inv(_matrix(cd))

    def pixels(displacement: np.ndarray) -> tuple[float, float]:
        # The sky moves under the telescope the opposite way to the telescope.
        sky = -np.degrees([np.dot(displacement, east), np.dot(displacement, north)])
        dx, dy = inverse @ sky
        return float(dx), float(dy)

    return StarMoves(az=pixels(d_az), alt=pixels(d_alt))
