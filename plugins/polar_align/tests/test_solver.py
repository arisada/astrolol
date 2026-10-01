"""Unit tests for polar_align.solver, validated against astropy as an independent oracle.

No mount, no simulator, no INDI. Ground truth is built from a "mount-frame" sequence -- the RA
the mount *reports itself at* (as if its own axis were the true pole) -- rotated into the sky by
an injected (alt_err, az_err) misalignment, exactly mirroring the real geometry: a mount reports
RA assuming it IS correctly aligned, while the true sky position it points at differs by whatever
its real axis is off by. astropy's AltAz transform (not solver.py's own code) places the injected
axis on the sky.

Each observation also gets an independently-chosen wall-clock timestamp, decoupled from the
mount-frame RA used to build it: under tracking, the mount's self-reported RA stays the same
regardless of elapsed time (that's what tracking means), so the same mount-frame RA can be
stamped with any timestamp/gap at all and must still fit correctly -- this is what makes B1
(solver.py must derive rotation from elapsed time *combined with* the mount's own reported RA,
not from the solved position's Hour Angle, and not from the mount's reported RA delta alone)
directly testable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from astropy.coordinates import FK5, AltAz, EarthLocation, SkyCoord
from astropy.time import Time
import astropy.units as u

from astrolol.mount.sky import local_sidereal_time_h
from plugins.polar_align.solver import Observation, _refine_axis, fit_pole_offset, update_pole_offset

LATITUDE = 45.0
LONGITUDE = 5.0
WHEN = datetime(2026, 6, 1, 22, 0, 0, tzinfo=timezone.utc)
SITE = EarthLocation(lat=LATITUDE * u.deg, lon=LONGITUDE * u.deg, height=200 * u.m)
TIME = Time(WHEN)


def _rotation_aligning_z_to(target: np.ndarray) -> np.ndarray:
    """Matrix mapping the +z axis onto the given unit vector (independent of solver.py)."""
    z = np.array([0.0, 0.0, 1.0])
    axis = np.cross(z, target)
    sin_t = np.linalg.norm(axis)
    cos_t = np.dot(z, target)
    if sin_t < 1e-12:
        return np.eye(3) if cos_t > 0 else -np.eye(3)
    axis = axis / sin_t
    k = np.array(
        [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    )
    return np.eye(3) + k * sin_t + k @ k * (1 - cos_t)


def _radec_to_vector(ra_hours: float, dec_deg: float) -> np.ndarray:
    ra, dec = np.radians(ra_hours * 15.0), np.radians(dec_deg)
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def _vector_to_radec(v: np.ndarray) -> tuple[float, float]:
    v = v / np.linalg.norm(v)
    dec = np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0)))
    ra = np.degrees(np.arctan2(v[1], v[0])) / 15.0 % 24.0
    return float(ra), float(dec)


def _injected_axis_coord(alt_err_arcmin: float, az_err_arcmin: float, latitude_deg: float = LATITUDE) -> SkyCoord:
    pole_sign = 1.0 if latitude_deg >= 0 else -1.0
    axis_alt = pole_sign * latitude_deg + alt_err_arcmin / 60.0
    axis_az = (0.0 if latitude_deg >= 0 else 180.0) + az_err_arcmin / 60.0
    site = EarthLocation(lat=latitude_deg * u.deg, lon=LONGITUDE * u.deg, height=200 * u.m)
    return SkyCoord(alt=axis_alt * u.deg, az=axis_az * u.deg, frame=AltAz(obstime=TIME, location=site)).transform_to(
        FK5(equinox=TIME)
    )


def _synthesize(
    alt_err_arcmin: float,
    az_err_arcmin: float,
    mount_ra_sequence_deg: list[float],
    *,
    mount_dec_deg: float = 0.0,
    latitude_deg: float = LATITUDE,
    timestamps: list[datetime] | None = None,
) -> tuple[list[Observation], SkyCoord]:
    """Build Observations for a mount whose real axis is offset by the given amount.

    ``mount_ra_sequence_deg`` is what the mount reports itself at for each point (as if its own
    axis were the true pole) -- this is the slew-command design variable, entirely independent
    of wall-clock time. ``timestamps`` (defaulting to the same instant for all, if omitted) is
    then stamped on independently: a mount holding one of these RA values under tracking reports
    the *same* mount_ra_hours no matter how much time passes, while the true sky position (and
    therefore what a plate solve run at that moment reports) is fixed by the rotation alone, not
    by elapsed time either. The solver must still recover the correct rotation regardless of
    what timestamps/gaps are stamped on the same mount-frame sequence.
    """
    if timestamps is None:
        timestamps = [WHEN] * len(mount_ra_sequence_deg)
    axis_coord = _injected_axis_coord(alt_err_arcmin, az_err_arcmin, latitude_deg)
    rotation = _rotation_aligning_z_to(axis_coord.cartesian.xyz.value)

    observations = []
    for mount_ra_deg, when in zip(mount_ra_sequence_deg, timestamps):
        mount_ra_hours = mount_ra_deg / 15.0
        # The mount's true shaft angle (what the misalignment rotation actually acts on) is
        # mount_ra - LST, not mount_ra directly: a mount tracking at a fixed reported RA keeps
        # physically turning as time passes (LST advances), even though mount_ra_hours itself
        # doesn't change -- see solver.py's module docstring for the full derivation.
        shaft_angle_hours = mount_ra_hours - local_sidereal_time_h(when, LONGITUDE)
        p_mount = _radec_to_vector(shaft_angle_hours, mount_dec_deg)
        p_true = rotation @ p_mount
        solved_ra_hours, solved_dec_deg = _vector_to_radec(p_true)
        observations.append(
            Observation(
                solved_ra_hours=solved_ra_hours,
                solved_dec_deg=solved_dec_deg,
                mount_ra_hours=mount_ra_hours,
                when=when,
            )
        )
    return observations, axis_coord


@pytest.mark.parametrize(
    "alt_err_arcmin,az_err_arcmin",
    [
        (0.0, 0.0),
        (30.0, 0.0),
        (0.0, 30.0),
        (30.0, 30.0),
        (-45.0, 20.0),
        (300.0, -150.0),
    ],
)
def test_recovers_injected_axis_two_points(alt_err_arcmin: float, az_err_arcmin: float) -> None:
    observations, axis_coord = _synthesize(alt_err_arcmin, az_err_arcmin, [0.0, 45.0], mount_dec_deg=30.0)
    result = fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)

    assert result.axis_ra_hours == pytest.approx(axis_coord.ra.hour, abs=1e-6)
    assert result.axis_dec_deg == pytest.approx(axis_coord.dec.deg, abs=1e-4)
    assert result.alt_error_arcmin == pytest.approx(alt_err_arcmin, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(az_err_arcmin, abs=1.5)


def test_recovers_injected_axis_three_points() -> None:
    observations, axis_coord = _synthesize(40.0, -25.0, [0.0, 45.0, 100.0], mount_dec_deg=10.0)
    result = fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)

    assert result.axis_ra_hours == pytest.approx(axis_coord.ra.hour, abs=1e-6)
    assert result.axis_dec_deg == pytest.approx(axis_coord.dec.deg, abs=1e-4)
    assert result.alt_error_arcmin == pytest.approx(40.0, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(-25.0, abs=1.5)


@pytest.mark.parametrize("target_dec", [-30.0, 30.0, 60.0])
def test_recovers_axis_at_various_declinations(target_dec: float) -> None:
    observations, _ = _synthesize(50.0, 50.0, [0.0, 60.0], mount_dec_deg=target_dec)
    result = fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)

    assert result.alt_error_arcmin == pytest.approx(50.0, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(50.0, abs=1.5)


@pytest.mark.parametrize("slew_deg", [15.0, 60.0, 90.0, 135.0])
def test_recovers_axis_for_various_slew_amounts(slew_deg: float) -> None:
    observations, _ = _synthesize(35.0, -15.0, [0.0, slew_deg], mount_dec_deg=30.0)
    result = fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)

    assert result.alt_error_arcmin == pytest.approx(35.0, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(-15.0, abs=1.5)


def test_slew_too_close_to_half_turn_raises() -> None:
    observations, _ = _synthesize(35.0, -15.0, [0.0, 178.5], mount_dec_deg=30.0)
    with pytest.raises(ValueError):
        fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)


def test_zero_error_recovers_true_pole() -> None:
    observations, _ = _synthesize(0.0, 0.0, [0.0, 60.0], mount_dec_deg=30.0)
    result = fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)

    assert result.alt_error_arcmin == pytest.approx(0.0, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(0.0, abs=1.5)


def test_negating_error_negates_recovered_error() -> None:
    observations_pos, _ = _synthesize(40.0, 20.0, [0.0, 60.0], mount_dec_deg=30.0)
    observations_neg, _ = _synthesize(-40.0, -20.0, [0.0, 60.0], mount_dec_deg=30.0)

    result_pos = fit_pole_offset(observations_pos, LATITUDE, LONGITUDE, WHEN)
    result_neg = fit_pole_offset(observations_neg, LATITUDE, LONGITUDE, WHEN)

    assert result_neg.alt_error_arcmin == pytest.approx(-result_pos.alt_error_arcmin, abs=1.5)
    assert result_neg.az_error_arcmin == pytest.approx(-result_pos.az_error_arcmin, abs=1.5)


def test_reordering_observations_does_not_change_magnitude() -> None:
    forward, _ = _synthesize(30.0, 15.0, [0.0, 60.0], mount_dec_deg=30.0)
    reversed_obs = list(reversed(forward))

    result_forward = fit_pole_offset(forward, LATITUDE, LONGITUDE, WHEN)
    result_reversed = fit_pole_offset(reversed_obs, LATITUDE, LONGITUDE, WHEN)

    assert result_reversed.alt_error_arcmin == pytest.approx(result_forward.alt_error_arcmin, abs=1.5)
    assert result_reversed.az_error_arcmin == pytest.approx(result_forward.az_error_arcmin, abs=1.5)


def test_too_few_observations_raises() -> None:
    observations, _ = _synthesize(10.0, 10.0, [0.0], mount_dec_deg=30.0)
    with pytest.raises(ValueError):
        fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)


def test_negligible_slew_raises() -> None:
    observations, _ = _synthesize(10.0, 10.0, [0.0, 0.3], mount_dec_deg=30.0)
    with pytest.raises(ValueError):
        fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)


# ===========================================================================
# B2 -- a 2-point fit near the equator is rejected rather than silently wrong.
# ===========================================================================


@pytest.mark.parametrize("target_dec", [-10.0, 0.0, 15.0])
def test_two_point_fit_near_equator_raises(target_dec: float) -> None:
    observations, _ = _synthesize(30.0, 20.0, [0.0, 60.0], mount_dec_deg=target_dec)
    with pytest.raises(ValueError):
        fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)


def test_three_point_fit_near_equator_is_allowed() -> None:
    observations, _ = _synthesize(30.0, 20.0, [0.0, 60.0, 120.0], mount_dec_deg=0.0)
    result = fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)
    assert result.alt_error_arcmin == pytest.approx(30.0, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(20.0, abs=1.5)


# ===========================================================================
# B1 -- the fit must be correct regardless of the wall-clock gap between
# observations (tracking holds the mount's *reported* RA constant while its
# axis keeps physically rotating -- solver.py must not be fooled by that).
# ===========================================================================


@pytest.mark.parametrize("gap_minutes", [0.0, 1.0, 3.0, 10.0, 30.0])
def test_fit_is_accurate_regardless_of_time_gap_between_observations(gap_minutes: float) -> None:
    timestamps = [WHEN, WHEN + timedelta(minutes=gap_minutes), WHEN + timedelta(minutes=2 * gap_minutes)]
    observations, _ = _synthesize(
        35.0, -20.0, [0.0, 60.0, 120.0], mount_dec_deg=30.0, timestamps=timestamps
    )
    # Report "now" at the original WHEN, matching how the injected axis's alt/az was defined --
    # alt/az of a fixed sky point genuinely changes over the gap, so reporting at a *later*
    # moment than the injected axis was defined at would (correctly) show a different alt/az;
    # that's a reporting-time mismatch, not something the fit itself got wrong.
    result = fit_pole_offset(observations, LATITUDE, LONGITUDE, WHEN)

    assert result.alt_error_arcmin == pytest.approx(35.0, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(-20.0, abs=1.5)


def test_fit_matches_across_different_gap_patterns() -> None:
    """Same injected error and same ground-fixed HA sequence, wildly different timestamp
    gaps -- a correct solver must land on the same answer regardless (this is what the old,
    mount-reported-RA-delta approach could not do: it only ever saw the deliberate slew
    amount, never the extra rotation accumulated while tracking held position between
    exposures)."""
    ha_sequence = [0.0, 60.0, 120.0]
    tight = [WHEN, WHEN + timedelta(seconds=5), WHEN + timedelta(seconds=10)]
    loose = [WHEN, WHEN + timedelta(minutes=15), WHEN + timedelta(hours=2)]

    obs_tight, _ = _synthesize(35.0, -20.0, ha_sequence, mount_dec_deg=30.0, timestamps=tight)
    obs_loose, _ = _synthesize(35.0, -20.0, ha_sequence, mount_dec_deg=30.0, timestamps=loose)

    result_tight = fit_pole_offset(obs_tight, LATITUDE, LONGITUDE, WHEN)
    result_loose = fit_pole_offset(obs_loose, LATITUDE, LONGITUDE, WHEN)

    assert result_tight.alt_error_arcmin == pytest.approx(result_loose.alt_error_arcmin, abs=1.5)
    assert result_tight.az_error_arcmin == pytest.approx(result_loose.az_error_arcmin, abs=1.5)
    assert result_tight.alt_error_arcmin == pytest.approx(35.0, abs=1.5)
    assert result_loose.az_error_arcmin == pytest.approx(-20.0, abs=1.5)


# ===========================================================================
# B3 -- the 3-point refinement must not get stuck exactly at the pole, where
# the old (ra, dec)-parameterized Gauss-Newton had a vanishing Jacobian.
# ===========================================================================


def test_refine_axis_does_not_freeze_at_pole_starting_point() -> None:
    """Start the Gauss-Newton refinement from an axis exactly AT the pole (the worst case
    for an (ra, dec) parameterization) and confirm it still moves to the correct, nearby,
    off-pole axis rather than reporting a spurious zero error."""
    observations, axis_coord = _synthesize(36.0, 0.0, [0.0, 60.0, 120.0], mount_dec_deg=20.0)
    vectors = [_radec_to_vector(o.solved_ra_hours, o.solved_dec_deg) for o in observations]
    mount_pseudo_ra = [o.mount_ra_hours - local_sidereal_time_h(o.when, LONGITUDE) for o in observations]
    thetas = [np.radians((p - mount_pseudo_ra[0]) * 15.0) for p in mount_pseudo_ra[1:]]

    pole_seed = np.array([0.0, 0.0, 1.0])
    refined = _refine_axis(pole_seed, vectors, thetas)

    dec_at_pole = np.degrees(np.arcsin(np.clip(refined[2], -1.0, 1.0)))
    assert dec_at_pole != pytest.approx(90.0, abs=1e-6), "refinement got stuck exactly at the pole"
    assert dec_at_pole == pytest.approx(axis_coord.dec.deg, abs=0.1)


@pytest.mark.parametrize("seed", [20260930, 20260931, 20260932])
def test_three_point_fit_robust_to_noise_near_pole(seed: int) -> None:
    """Inject small per-observation noise (plate-solve precision) on top of a realistic
    near-pole geometry and confirm the fit stays close -- this is the scenario where the
    old (ra, dec)-parameterized refinement could silently converge to dec=90 with noise."""
    rng = np.random.default_rng(seed)
    observations, _ = _synthesize(35.0, 20.0, [0.0, 60.0, 120.0], mount_dec_deg=25.0)
    noisy = []
    for o in observations:
        noisy.append(
            Observation(
                solved_ra_hours=o.solved_ra_hours + rng.normal(0, 10.0 / 3600 / 15),
                solved_dec_deg=o.solved_dec_deg + rng.normal(0, 10.0 / 3600),
                mount_ra_hours=o.mount_ra_hours,
                when=o.when,
            )
        )
    result = fit_pole_offset(noisy, LATITUDE, LONGITUDE, WHEN)
    assert result.alt_error_arcmin == pytest.approx(35.0, abs=3.0)
    assert result.az_error_arcmin == pytest.approx(20.0, abs=3.0)
    assert abs(result.axis_dec_deg) < 89.99, "fit collapsed onto the pole under noise"


# ===========================================================================
# B4 -- the solver must work for southern-hemisphere sites, not just northern.
# ===========================================================================


@pytest.mark.parametrize(
    "alt_err_arcmin,az_err_arcmin",
    [(0.0, 0.0), (30.0, 20.0), (-25.0, 40.0)],
)
def test_recovers_injected_axis_southern_hemisphere(alt_err_arcmin: float, az_err_arcmin: float) -> None:
    south_lat = -30.0
    observations, axis_coord = _synthesize(
        alt_err_arcmin, az_err_arcmin, [0.0, 60.0, 120.0], mount_dec_deg=-20.0, latitude_deg=south_lat
    )
    result = fit_pole_offset(observations, south_lat, LONGITUDE, WHEN)

    assert result.alt_error_arcmin == pytest.approx(alt_err_arcmin, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(az_err_arcmin, abs=1.5)


def test_random_sweep_recovers_injected_error() -> None:
    """Cheap extra net beyond the hand-picked cases above."""
    rng = np.random.default_rng(20260930)
    for _ in range(50):
        alt_err = rng.uniform(-90.0, 90.0)
        az_err = rng.uniform(-180.0, 180.0)
        target_dec = rng.uniform(-70.0, 70.0)
        latitude = rng.choice([LATITUDE, -LATITUDE])
        ha0 = rng.uniform(0.0, 360.0)
        # Bounded to [30, 70] (not up to 150) so the cumulative 2-step span for the 3-point
        # case (up to 140) stays well clear of the 180-degree degenerate guard band.
        step = rng.choice([-1, 1]) * rng.uniform(30.0, 70.0)
        # Margin beyond solver.py's own 20deg cutoff: the injected error can shift the
        # *solved* dec slightly away from the mount-frame target_dec checked here.
        if abs(target_dec) < 25.0:
            ha_sequence = [ha0, ha0 + step, ha0 + 2 * step]
        else:
            ha_sequence = [ha0, ha0 + step]

        observations, _ = _synthesize(alt_err, az_err, ha_sequence, mount_dec_deg=target_dec, latitude_deg=latitude)
        result = fit_pole_offset(observations, latitude, LONGITUDE, WHEN)

        assert result.alt_error_arcmin == pytest.approx(alt_err, abs=1.5)
        assert result.az_error_arcmin == pytest.approx(az_err, abs=1.5)


# ===========================================================================
# update_pole_offset -- the CONVERGING-phase knob-adjustment measurement.
#
# Independent oracle here is built differently from the main fit's: the "knob rotation"
# is constructed with a freshly-written Rodrigues implementation (not imported from
# solver.py) operating directly in alt/az terms (where an azimuth-knob rotation is
# exactly "shift az, keep alt" and an altitude-knob rotation is a rotation about a known
# horizontal axis), and astropy's AltAz<->FK5 transform (not solver.py's sky.alt_az) is
# the oracle for converting alt/az to JNow RA/Dec.
# ===========================================================================


def _own_rodrigues(axis: np.ndarray, theta: float, v: np.ndarray) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    return v * np.cos(theta) + np.cross(axis, v) * np.sin(theta) + axis * np.dot(axis, v) * (1 - np.cos(theta))


def _altaz_to_vector(alt_deg: float, az_deg: float) -> np.ndarray:
    alt_r, az_r = np.radians(alt_deg), np.radians(az_deg)
    return np.array([np.cos(alt_r) * np.sin(az_r), np.cos(alt_r) * np.cos(az_r), np.sin(alt_r)])


def _vector_to_altaz(v: np.ndarray) -> tuple[float, float]:
    v = v / np.linalg.norm(v)
    alt = np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0)))
    az = np.degrees(np.arctan2(v[0], v[1])) % 360.0
    return float(alt), float(az)


def _apply_knob_rotation(
    alt_deg: float, az_deg: float, bearing_deg: float, d_az_deg: float, d_alt_deg: float
) -> tuple[float, float]:
    """Independent reimplementation of the same physical model update_pole_offset
    assumes: a rigid-body tip about the local vertical (azimuth knob) composed with a
    rotation about the horizontal axis perpendicular to `bearing_deg` (altitude knob)."""
    v = _altaz_to_vector(alt_deg, az_deg)
    zenith = np.array([0.0, 0.0, 1.0])
    bearing_r = np.radians(bearing_deg)
    alt_axis = np.array([np.cos(bearing_r), -np.sin(bearing_r), 0.0])
    v = _own_rodrigues(zenith, np.radians(d_az_deg), v)
    v = _own_rodrigues(alt_axis, np.radians(d_alt_deg), v)
    return _vector_to_altaz(v)


def _altaz_to_jnow(alt_deg: float, az_deg: float, latitude_deg: float) -> tuple[float, float]:
    site = EarthLocation(lat=latitude_deg * u.deg, lon=LONGITUDE * u.deg, height=200 * u.m)
    coord = SkyCoord(alt=alt_deg * u.deg, az=az_deg * u.deg, frame=AltAz(obstime=TIME, location=site)).transform_to(
        FK5(equinox=TIME)
    )
    return float(coord.ra.hour), float(coord.dec.deg)


def _convergence_case(
    alt_err0_arcmin: float,
    az_err0_arcmin: float,
    d_az_deg: float,
    d_alt_deg: float,
    ref_alt_deg: float = 45.0,
    # Not 90: that's alt_axis's own azimuth (bearing +/- 90), the exact mirror-symmetric
    # degeneracy update_pole_offset now rejects (see _MIN_SEP_FROM_SYMMETRIC_PLANE_DEG).
    ref_az_offset_deg: float = 45.0,
    latitude_deg: float = LATITUDE,
):
    pole_sign = 1.0 if latitude_deg >= 0 else -1.0
    axis_alt0 = pole_sign * latitude_deg + alt_err0_arcmin / 60.0
    axis_az0 = (0.0 if latitude_deg >= 0 else 180.0) + az_err0_arcmin / 60.0
    ref_alt0, ref_az0 = ref_alt_deg, (axis_az0 + ref_az_offset_deg) % 360.0

    axis_ra_h, axis_dec = _altaz_to_jnow(axis_alt0, axis_az0, latitude_deg)
    ref_ra_h, ref_dec = _altaz_to_jnow(ref_alt0, ref_az0, latitude_deg)

    new_axis_alt, new_axis_az = _apply_knob_rotation(axis_alt0, axis_az0, axis_az0, d_az_deg, d_alt_deg)
    new_ref_alt, new_ref_az = _apply_knob_rotation(ref_alt0, ref_az0, axis_az0, d_az_deg, d_alt_deg)
    new_ra_h, new_dec = _altaz_to_jnow(new_ref_alt, new_ref_az, latitude_deg)

    true_pole_dec = 90.0 if latitude_deg >= 0 else -90.0
    from astrolol.mount.sky import alt_az as _alt_az

    true_alt, true_az = _alt_az(0.0, true_pole_dec, latitude_deg)
    expected_alt_error = (new_axis_alt - true_alt) * 60.0
    expected_az_error = ((new_axis_az - true_az + 180.0) % 360.0 - 180.0) * 60.0

    return axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, expected_alt_error, expected_az_error


@pytest.mark.parametrize(
    "alt_err0,az_err0,d_az,d_alt",
    [
        (20.0, 15.0, 0.0, 0.0),
        (20.0, 15.0, 9.0, 0.0),
        (20.0, 15.0, 0.0, -8.0),
        (20.0, 15.0, -8.0, 6.0),
        (-30.0, 40.0, 5.0, -5.0),
        (60.0, -20.0, 8.0, 8.0),
    ],
)
def test_update_pole_offset_matches_independent_oracle(
    alt_err0: float, az_err0: float, d_az: float, d_alt: float
) -> None:
    axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, exp_alt, exp_az = _convergence_case(
        alt_err0, az_err0, d_az, d_alt
    )
    result = update_pole_offset(axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, LATITUDE, LONGITUDE, WHEN)

    assert result.alt_error_arcmin == pytest.approx(exp_alt, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(exp_az, abs=1.5)


def test_update_pole_offset_zero_knob_rotation_is_a_noop() -> None:
    axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, exp_alt, exp_az = _convergence_case(
        25.0, -10.0, 0.0, 0.0
    )
    result = update_pole_offset(axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, LATITUDE, LONGITUDE, WHEN)

    assert result.alt_error_arcmin == pytest.approx(25.0, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(-10.0, abs=1.5)


def test_update_pole_offset_southern_hemisphere() -> None:
    axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, exp_alt, exp_az = _convergence_case(
        15.0, -25.0, -8.0, 6.0, latitude_deg=-LATITUDE
    )
    result = update_pole_offset(
        axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, -LATITUDE, LONGITUDE, WHEN
    )

    assert result.alt_error_arcmin == pytest.approx(exp_alt, abs=1.5)
    assert result.az_error_arcmin == pytest.approx(exp_az, abs=1.5)


def test_update_pole_offset_rejects_reference_near_zenith() -> None:
    axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, _, _ = _convergence_case(
        10.0, 10.0, 5.0, 5.0, ref_alt_deg=89.0
    )
    with pytest.raises(ValueError, match="zenith"):
        update_pole_offset(axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, LATITUDE, LONGITUDE, WHEN)


def test_update_pole_offset_rejects_reference_near_alt_axis() -> None:
    # alt_axis (horizontal, perpendicular to the bearing) points at azimuth bearing+90,
    # altitude 0 -- a reference near THAT azimuth and near the horizon is what's nearly
    # aligned with it, not a reference at the bearing's own azimuth (that's actually the
    # best-conditioned direction, since it's as far from alt_axis as azimuth allows).
    axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, _, _ = _convergence_case(
        10.0, 10.0, 5.0, 5.0, ref_alt_deg=2.0, ref_az_offset_deg=90.0
    )
    with pytest.raises(ValueError, match="altitude-knob"):
        update_pole_offset(axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, LATITUDE, LONGITUDE, WHEN)


def test_update_pole_offset_rejects_implausibly_large_adjustment() -> None:
    # The 2-solution ambiguity picks the wrong root for some geometries once the
    # rotation gets this large (confirmed directly: both candidates are exact solutions,
    # minimum-norm selection isn't reliably the physical one any more) -- large enough
    # that it isn't a realistic single knob nudge between rechecks either way.
    axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, _, _ = _convergence_case(
        60.0, -20.0, 20.0, 20.0
    )
    with pytest.raises(ValueError, match="knob adjustment"):
        update_pole_offset(axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, LATITUDE, LONGITUDE, WHEN)


def test_update_pole_offset_random_sweep() -> None:
    """With the injected axis kept close to the pole (realistic: fine-tuning an already
    roughly-aligned mount), azimuth itself is somewhat numerically sensitive -- the same
    effect fit_pole_offset's own near-pole tests have to account for -- so a conditioning
    guard legitimately rejecting a handful of random draws is expected, not a failure;
    what matters is that it doesn't reject *most* of them, and that every accepted draw
    is correct."""
    rng = np.random.default_rng(20261001)
    rejected = 0
    checked = 0
    for _ in range(50):
        alt_err0 = rng.uniform(-80.0, 80.0)
        az_err0 = rng.uniform(-170.0, 170.0)
        # Within the realistic knob-adjustment range update_pole_offset actually targets
        # (see _MAX_PLAUSIBLE_KNOB_ADJUSTMENT_DEG) -- a dedicated test covers the guard
        # that rejects larger, ambiguity-prone implied adjustments.
        d_az = rng.uniform(-7.0, 7.0)
        d_alt = rng.uniform(-7.0, 7.0)
        ref_alt = rng.uniform(20.0, 70.0)
        ref_az_offset = rng.choice([45.0, 60.0, 120.0, 135.0, 225.0, 240.0, 300.0, 315.0])
        latitude = rng.choice([LATITUDE, -LATITUDE])

        axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, exp_alt, exp_az = _convergence_case(
            alt_err0, az_err0, d_az, d_alt, ref_alt_deg=ref_alt, ref_az_offset_deg=ref_az_offset,
            latitude_deg=latitude,
        )
        try:
            result = update_pole_offset(
                axis_ra_h, axis_dec, ref_ra_h, ref_dec, new_ra_h, new_dec, latitude, LONGITUDE, WHEN
            )
        except ValueError:
            rejected += 1
            continue
        checked += 1
        assert result.alt_error_arcmin == pytest.approx(exp_alt, abs=1.5)
        assert result.az_error_arcmin == pytest.approx(exp_az, abs=1.5)

    assert checked >= 35, f"too many of 50 draws were rejected by a conditioning guard ({rejected})"
