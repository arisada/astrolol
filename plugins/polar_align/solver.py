"""Three-point polar-alignment solver.

As an equatorial mount's RA axis physically rotates between two observations
(whether from a deliberate slew or just from tracking holding a target across
elapsed time), a fixed target's plate-solved sky position traces an arc
around the mount's *actual* (possibly misaligned) mechanical axis. Two solved
observations plus the true rotation angle between them are enough to locate
that axis on the sky; a third observation turns the 2-point closed-form
solution into an over-determined least-squares fit that also absorbs
plate-solve noise.

The observed *vectors* are the plate-solved sky positions directly (RA/Dec,
sky-fixed) -- that part is simple. The rotation *angle* between observations
is not: naively using the mount's self-reported RA delta is wrong, because a
mount actively tracking a target holds its reported RA/Dec ~constant by
definition (that is what tracking means), even though its RA-axis motor
keeps physically turning at the sidereal rate to do so -- the self-reported
delta hides exactly the rotation a fit needs. Conversely, computing the
rotation purely from how much the *solved* position's Hour Angle changed is
also wrong: rotating a point by theta about a *tilted* axis does not change
its standard-frame HA reading by exactly theta (only a perfectly aligned
axis has that property), so HA-of-the-solve is not theta either. What does
work: elapsed sidereal time (always accruing, tracked or not) combined with
the mount's own self-reported RA delta, i.e. local sidereal time minus the
mount's reported RA -- the mount's self-reported *Hour Angle*. That
correctly nets out to the true motor rotation whether the elapsed interval
was spent tracking, slewing, or both.

Pure math only: no device I/O, no plugin state. ``wizard.py`` is the only
caller and is responsible for collecting ``Observation``s from the mount and
plate solver, and separately for verifying the mount-side preconditions this
module cannot see (unchanged pier side, unchanged Dec, no sync mid-run).

All RA/Dec here must be JNow (equinox of date), matching ``MountStatus.ra_jnow``/
``dec_jnow``: the final alt/az step uses ``astrolol.mount.sky.alt_az``, which is
deliberately precession-free and assumes its inputs are already frame-of-date.
Plate-solve results are typically J2000/ICRS and must be precessed via
``astrolol.mount.sky.icrs_to_jnow`` before being passed in here, or the missing
precession correction shows up as a spurious multi-arcminute error.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
from pydantic import BaseModel, Field

from astrolol.mount.sky import alt_az, local_sidereal_time_h

_MIN_SLEW_RAD = np.radians(1.0)  # observations closer together than this are too noise-sensitive
_MAX_SLEW_FROM_180_RAD = np.radians(5.0)  # near an exact half-turn the fit axis is degenerate
_MIN_DEC_FOR_TWO_POINT_DEG = 20.0  # below this, a 2-point fit is too close to the equator-degenerate case


class Observation(BaseModel):
    """One plate-solved data point taken during the wizard's RA-slew sequence."""

    solved_ra_hours: float = Field(description="Plate-solved RA, JNow -- where the telescope truly points")
    solved_dec_deg: float = Field(description="Plate-solved Dec, JNow")
    mount_ra_hours: float = Field(description="Mount's own reported RA (JNow) at solve time")
    when: datetime = Field(description="UTC time this observation was taken (exposure midpoint)")


class PoleOffset(BaseModel):
    """Where the mount's actual mechanical pole is, and how far that is from true."""

    axis_ra_hours: float
    axis_dec_deg: float
    alt_error_arcmin: float = Field(description="Axis altitude minus true pole altitude")
    az_error_arcmin: float = Field(description="Axis azimuth minus true pole azimuth, wrapped to +-180deg")


def fit_pole_offset(
    observations: list[Observation],
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
) -> PoleOffset:
    """Recover the mount's actual polar-axis offset from >=2 observations.

    Observations should share a fixed Dec target and differ mainly in RA
    (the wizard's own job: keep Dec unchanged and verify it stayed that way),
    but this function only relies on each observation's mount-reported Hour
    Angle (mount_ra_hours combined with its own timestamp), not on any
    particular Dec pattern. ``when`` (for the final alt/az conversion) need
    not match any observation's own timestamp -- it is "now", for reporting
    the error as it stands at call time.
    """
    if len(observations) < 2:
        raise ValueError("need at least 2 observations to fit a pole offset")
    if len(observations) == 2 and abs(observations[0].solved_dec_deg) < _MIN_DEC_FOR_TWO_POINT_DEG:
        raise ValueError(
            f"a 2-point fit is unreliable within {_MIN_DEC_FOR_TWO_POINT_DEG:g}deg of the equator "
            "(the fit is nearly degenerate there) -- use 3 points, or a target further from the equator"
        )

    # The observed sky vectors are built directly from the plate-solved RA/Dec (sky-fixed) --
    # that part was never the problem. What needed fixing is theta: the mount's own axis motor
    # rotation between observations. Rotating a point by theta about a *tilted* axis does not
    # change its standard-frame HA reading by exactly theta (only by zero misalignment would it),
    # so theta cannot be read off the solved positions themselves. It has to come from how far
    # the mount's own axis really turned, which combines two things: the mount's self-reported
    # RA change (a deliberate slew moves it directly) minus elapsed sidereal time (since holding
    # a fixed reported RA under tracking requires the motor to keep turning to cancel exactly
    # that drift -- see simulator.py's _effective_ra for the equivalent reasoning in reverse:
    # a *stationary* axis's apparent RA increases with elapsed time, so actively cancelling that
    # to hold RA constant means the motor contributes the negative of it).
    mount_pseudo_ra = [o.mount_ra_hours - local_sidereal_time_h(o.when, longitude_deg) for o in observations]
    vectors = [_radec_to_vector(o.solved_ra_hours, o.solved_dec_deg) for o in observations]
    thetas = [np.radians((p_i - mount_pseudo_ra[0]) * 15.0) for p_i in mount_pseudo_ra[1:]]
    for theta in thetas:
        wrapped = abs(_wrap_pm_pi(theta))
        if wrapped < _MIN_SLEW_RAD:
            raise ValueError("observations must be separated by a substantial RA-axis rotation (>=1deg)")
        if abs(wrapped - np.pi) < _MAX_SLEW_FROM_180_RAD:
            raise ValueError(
                "RA-axis rotation too close to an exact half-turn (180deg) -- the fit axis is "
                "degenerate there; use a slew closer to 60-90deg"
            )

    # A bare 2-point fit is not always unique: distinct axes can satisfy the same
    # (angular separation, rotation angle) pair exactly. A real mount's actual pole is
    # always close to true north/south (that's what a rough polar-scope pre-alignment
    # is for), so break ties toward the expected pole rather than picking arbitrarily.
    expected_pole = np.array([0.0, 0.0, 1.0 if latitude_deg >= 0 else -1.0])
    axis = _two_point_axis(vectors[0], vectors[1], thetas[0], expected_pole)
    if len(vectors) > 2:
        axis = _refine_axis(axis, vectors, thetas)

    # axis is in the sky RA/Dec frame (same frame as the vectors above); convert to HA at
    # the reporting time `when` only for the final alt/az step.
    axis_ra_hours, axis_dec_deg = _vector_to_radec(axis)
    axis_ha = local_sidereal_time_h(when, longitude_deg) - axis_ra_hours
    axis_alt, axis_az = alt_az(axis_ha, axis_dec_deg, latitude_deg)
    true_pole_dec = 90.0 if latitude_deg >= 0 else -90.0
    true_alt, true_az = alt_az(0.0, true_pole_dec, latitude_deg)

    return PoleOffset(
        axis_ra_hours=axis_ra_hours,
        axis_dec_deg=axis_dec_deg,
        alt_error_arcmin=(axis_alt - true_alt) * 60.0,
        az_error_arcmin=np.degrees(_wrap_pm_pi(np.radians(axis_az - true_az))) * 60.0,
    )


def _radec_to_vector(ra_hours: float, dec_deg: float) -> np.ndarray:
    ra, dec = np.radians(ra_hours * 15.0), np.radians(dec_deg)
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def _vector_to_radec(v: np.ndarray) -> tuple[float, float]:
    v = v / np.linalg.norm(v)
    dec = np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0)))
    ra = np.degrees(np.arctan2(v[1], v[0])) / 15.0 % 24.0
    return float(ra), float(dec)


def _wrap_pm_pi(angle_rad: float) -> float:
    return float((angle_rad + np.pi) % (2 * np.pi) - np.pi)


def _rodrigues(axis: np.ndarray, theta: float, v: np.ndarray) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    return (
        v * np.cos(theta)
        + np.cross(axis, v) * np.sin(theta)
        + axis * np.dot(axis, v) * (1 - np.cos(theta))
    )


def _two_point_axis(p0: np.ndarray, p1: np.ndarray, theta: float, expected_pole: np.ndarray) -> np.ndarray:
    """Closed-form axis for a single (p0 -> p1 via rotation theta) pair.

    n is equidistant (angle alpha) from p0 and p1, with alpha fixed by the
    spherical chord relation cos(c) = cos^2(alpha) + sin^2(alpha)*cos(theta),
    c being the angular separation of p0 and p1. Since this relation only
    determines sin(alpha), both alpha and (pi - alpha) are candidate angular
    distances (the axis may be closer to p0/p1 or on the far side of the
    sphere from them) -- e.g. a near-polar axis is >90 degrees from a target
    near the celestial equator. n then lies on the great circle
    {x : x.(p0-p1) = 0}; of the (up to four) resulting candidate points, more
    than one can satisfy "rotates p0 to p1 by +theta" almost exactly -- this
    2-point problem is not always unique. Among those that do, the one closest
    to ``expected_pole`` is taken (see caller for why that prior is valid).
    """
    c = np.arccos(np.clip(np.dot(p0, p1), -1.0, 1.0))
    denom = 1 - np.cos(theta)
    sin2alpha = np.clip((1 - np.cos(c)) / denom, 0.0, 1.0)
    alpha_acute = np.arcsin(np.sqrt(sin2alpha))

    m = p0 + p1
    m = m / np.linalg.norm(m)
    normal = p0 - p1
    normal = normal / np.linalg.norm(normal)
    e2 = np.cross(normal, m)
    e2 = e2 / np.linalg.norm(e2)

    a, b = np.dot(m, p0), np.dot(e2, p0)
    radius = np.hypot(a, b)
    phi = np.arctan2(b, a)

    residual_ok = []
    for alpha in (alpha_acute, np.pi - alpha_acute):
        target = np.clip(np.cos(alpha) / radius, -1.0, 1.0)
        delta = np.arccos(target)
        for sign in (1.0, -1.0):
            beta = phi + sign * delta
            candidate = np.cos(beta) * m + np.sin(beta) * e2
            predicted = _rodrigues(candidate, theta, p0)
            err = np.linalg.norm(predicted - p1)
            residual_ok.append((err, candidate))

    min_err = min(err for err, _ in residual_ok)
    valid = [c for err, c in residual_ok if err < max(min_err * 10, 1e-9)]
    return max(valid, key=lambda c: np.dot(c, expected_pole))


def _refine_axis(
    axis0: np.ndarray, vectors: list[np.ndarray], thetas: list[float], iterations: int = 20
) -> np.ndarray:
    """Gauss-Newton refinement over all observations.

    Parameterized by a 2D tangent-plane offset (x, y) around the fixed starting
    axis0, not by (ra, dec) of the axis itself: axis0 is normally near a pole
    (that's the whole point of polar alignment), where RA is undefined and its
    Jacobian column vanishes, which can silently freeze the fit exactly at the
    pole. A tangent-plane offset around a Cartesian starting vector has no such
    singularity for any axis0 direction.
    """
    axis0 = axis0 / np.linalg.norm(axis0)
    seed = np.array([1.0, 0.0, 0.0]) if abs(axis0[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(axis0, seed)
    e1 = e1 / np.linalg.norm(e1)
    e2 = np.cross(axis0, e1)  # already unit: axis0 and e1 are orthonormal
    p0 = vectors[0]

    def axis_from_xy(x: float, y: float) -> np.ndarray:
        v = axis0 + x * e1 + y * e2
        return v / np.linalg.norm(v)

    def residuals(x: float, y: float) -> np.ndarray:
        axis = axis_from_xy(x, y)
        out = []
        for theta, target in zip(thetas, vectors[1:]):
            predicted = _rodrigues(axis, theta, p0)
            out.extend(predicted - target)
        return np.array(out)

    x, y = 0.0, 0.0
    step = 1e-6
    for _ in range(iterations):
        r0 = residuals(x, y)
        dx = (residuals(x + step, y) - r0) / step
        dy = (residuals(x, y + step) - r0) / step
        jacobian = np.column_stack([dx, dy])
        delta, *_ = np.linalg.lstsq(jacobian, -r0, rcond=None)
        x += delta[0]
        y += delta[1]
        if np.linalg.norm(delta) < 1e-10:
            break

    return axis_from_xy(x, y)
