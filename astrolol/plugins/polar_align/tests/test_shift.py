"""The star view's geometry: where a star must go for the knobs to remove the polar error."""
from __future__ import annotations

import numpy as np
import pytest

from astrolol.mount.sky import alt_az, local_sidereal_time_h
from astrolol.plugins.polar_align.shift import pointing_after_star_shift, star_moves
from astrolol.plugins.polar_align.solver import (
    Observation,
    _earth_to_altaz,
    _earth_vector,
    correction_displacements,
    update_pole_offset,
)
from astrolol.plugins.polar_align.tests.test_solver import (
    LATITUDE,
    LONGITUDE,
    WHEN,
    _altaz_to_jnow,
    _convergence_case,
    _vector_to_altaz,
    _MOUNT_RA_HOURS,
)

ARCSEC_DEG = 1.0 / 3600.0
# 2"/pixel, north up and east left: the usual view of the sky.
CD = (-2 * ARCSEC_DEG, 0.0, 0.0, 2 * ARCSEC_DEG)


@pytest.mark.parametrize("alt_err0,az_err0", [(20.0, 15.0), (-30.0, 40.0), (6.0, -9.0), (0.0, 12.0)])
def test_applying_the_correction_removes_the_error(alt_err0: float, az_err0: float) -> None:
    """Move the pointing as the knobs would, solve there, and nothing is left."""
    axis_ha, axis_dec, reference, _new, _a, _b = _convergence_case(alt_err0, az_err0, 0.0, 0.0)
    pointing = _earth_vector(reference.solved_ra_hours, reference.solved_dec_deg, WHEN, LONGITUDE)
    d_az, d_alt = correction_displacements(alt_err0, az_err0, pointing, LATITUDE)

    moved = _earth_to_altaz(pointing, LATITUDE) + d_az + d_alt
    alt, az = _vector_to_altaz(moved)
    ra_h, dec = _altaz_to_jnow(alt, az, LATITUDE)
    result = update_pole_offset(
        axis_ha, axis_dec, reference,
        Observation(solved_ra_hours=ra_h, solved_dec_deg=dec, mount_ra_hours=_MOUNT_RA_HOURS, when=WHEN),
        LATITUDE, LONGITUDE,
    )
    assert result.alt_error_arcmin == pytest.approx(0.0, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(0.0, abs=1.5)


def test_no_error_means_no_move() -> None:
    _, _, reference, *_ = _convergence_case(0.0, 0.0, 0.0, 0.0)
    moves = star_moves(0.0, 0.0, reference.solved_ra_hours, reference.solved_dec_deg, WHEN, LATITUDE, LONGITUDE, CD)
    assert moves.total == pytest.approx((0.0, 0.0), abs=1e-6)


def test_move_length_matches_the_error() -> None:
    """Fixing 10' of altitude error moves the field by about 10' (300 pixels at 2"/pixel)."""
    _, _, reference, *_ = _convergence_case(10.0, 0.0, 0.0, 0.0)
    moves = star_moves(10.0, 0.0, reference.solved_ra_hours, reference.solved_dec_deg, WHEN, LATITUDE, LONGITUDE, CD)
    # The field moves by up to the knob angle times the sine of its angle to the rotation axis.
    length = float(np.hypot(*moves.total))
    assert 0.2 * 300 < length <= 300 * 1.01
    assert moves.az == pytest.approx((0.0, 0.0), abs=1e-6)  # no azimuth error, so that knob does nothing


def test_a_mirrored_camera_mirrors_the_moves() -> None:
    _, _, reference, *_ = _convergence_case(15.0, -12.0, 0.0, 0.0)
    args = (15.0, -12.0, reference.solved_ra_hours, reference.solved_dec_deg, WHEN, LATITUDE, LONGITUDE)
    normal = star_moves(*args, CD)
    mirrored = star_moves(*args, (-CD[0], CD[1], CD[2], CD[3]))
    assert mirrored.total[0] == pytest.approx(-normal.total[0])
    assert mirrored.total[1] == pytest.approx(normal.total[1])


def test_moves_scale_with_pixel_size() -> None:
    _, _, reference, *_ = _convergence_case(15.0, -12.0, 0.0, 0.0)
    args = (15.0, -12.0, reference.solved_ra_hours, reference.solved_dec_deg, WHEN, LATITUDE, LONGITUDE)
    coarse = star_moves(*args, tuple(2 * c for c in CD))
    fine = star_moves(*args, CD)
    assert coarse.total[0] == pytest.approx(fine.total[0] / 2)
    assert coarse.total[1] == pytest.approx(fine.total[1] / 2)


def test_star_shift_and_pointing_agree() -> None:
    """A star that moves right in an image whose east is left: the telescope went east."""
    ra, dec = pointing_after_star_shift(6.0, 0.0, CD, 100.0, 0.0)
    assert ra > 6.0
    assert dec == pytest.approx(0.0)
    assert (ra - 6.0) * 15.0 == pytest.approx(100 * 2 * ARCSEC_DEG)
    # ... and a star that moves towards north (positive y here): the telescope went south.
    ra, dec = pointing_after_star_shift(6.0, 0.0, CD, 0.0, 100.0)
    assert dec < 0.0
