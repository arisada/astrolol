"""Calibration against a simulated mount: precision under seeing, slack, and what it reports."""
import asyncio
import math

import numpy as np
import pytest

from astrolol.plugins.guider.calibration import Calibration, CalibrationFailed, calibrate
from astrolol.plugins.guider.tests.rig import Rig


class Clock:
    """Simulated time: each measurement takes a frame, each pulse its length."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def run(rig: Rig, *, seeing: float = 0.0, seed: int = 0, drift=(0.0, 0.0), **kw) -> Calibration:  # noqa: ANN001, ANN003
    rng = np.random.default_rng(seed)
    clock = Clock()
    rig.drift_enabled = False

    async def measure():  # noqa: ANN202
        await asyncio.sleep(0)
        clock.t += 1.0  # a one-second frame
        x, y = rig.star_positions()[0]
        return (x + drift[0] * clock.t + rng.normal(0, seeing), y + drift[1] * clock.t + rng.normal(0, seeing))

    async def pulse(direction, ms):  # noqa: ANN001, ANN202
        rig.time_scale = 0
        await rig.pulse_guide(direction, ms)
        clock.t += ms / 1000

    return await calibrate(measure, pulse, clock=clock, **kw)


@pytest.mark.parametrize("seed", range(5))
async def test_calibration_is_precise_under_seeing(seed) -> None:
    # 0.3 px of seeing per frame, a slow drift and 0.005 px/ms (a 2"/px guide scope at 0.5x).
    matrix = np.array([[0.005 * math.cos(1.0), -0.005 * math.sin(1.0)], [0.005 * math.sin(1.0), 0.005 * math.cos(1.0)]])
    cal = await run(Rig(matrix=matrix), seeing=0.3, seed=seed, drift=(0.05, -0.03))
    assert np.allclose(cal.matrix, matrix, atol=0.0004), cal.matrix  # within 8% of the speed
    assert cal.quality is not None and cal.quality.residual_px < 0.6
    assert "noisy" not in cal.quality.issues


async def test_a_seeing_spike_does_not_set_the_step_length() -> None:
    # The first probe move is seeing; the probe must not take it for a pulse of 100 ms.
    rig = Rig(matrix=((0.002, 0), (0, 0.002)))
    cal = await run(rig, seeing=0.4, seed=11)
    assert cal.quality.ra_travel_px > 12 and cal.quality.dec_travel_px > 12
    assert cal.ra_rate == pytest.approx(0.002, rel=0.15)


async def test_large_dec_backlash_is_taken_up_before_the_north_sweep() -> None:
    cal = await run(Rig(dec_backlash_ms=1500))  # ten steps' worth of slack
    assert cal.dec_rate == pytest.approx(0.03, rel=0.03)
    assert cal.dec_backlash_ms == pytest.approx(1500, rel=0.1)
    assert all(p.used for p in cal.trace if p.phase == "north")  # the probe took the slack


async def test_ra_backlash_is_read_from_the_way_back() -> None:
    cal = await run(Rig(), seeing=0.0)
    assert cal.ra_backlash_ms == pytest.approx(0, abs=5)
    assert cal.dec_backlash_ms == pytest.approx(0, abs=5)


async def test_the_sweeps_go_on_until_the_star_moved_far_enough() -> None:
    # The probe sees a fast first move (a mount that starts quickly then settles at half speed
    # is modelled by halving the speed after the probe).
    rig = Rig()
    pulses = 0
    original = rig.pulse_guide

    async def slowing(direction, ms):  # noqa: ANN001, ANN202
        nonlocal pulses
        pulses += 1
        if pulses == 3:
            rig.matrix = rig.matrix / 2
        await original(direction, ms)

    rig.pulse_guide = slowing  # type: ignore[method-assign]
    cal = await run(rig, steps=5)
    assert cal.quality.ra_travel_px >= 0.6 * 25
    assert len([p for p in cal.trace if p.phase == "west"]) > 6


async def test_a_failed_calibration_keeps_its_points() -> None:
    with pytest.raises(CalibrationFailed) as info:
        await run(Rig(matrix=((0.03, 0.0), (0.0, 0.0))))  # Dec does nothing
    assert "N pulses" in str(info.value)
    phases = {p.phase for p in info.value.trace}
    assert {"drift", "probe", "west", "east"} <= phases


async def test_quality_flags_a_dec_speed_that_does_not_match_the_declination() -> None:
    cal = await run(Rig(), dec=60.0)  # RA should move half as fast as Dec at dec 60
    assert cal.quality.expected_ratio == pytest.approx(0.5, abs=0.01)
    assert "rate_ratio" in cal.quality.issues
    good = await run(Rig(matrix=((0.015, 0), (0, 0.03))), dec=60.0)
    assert "rate_ratio" not in good.quality.issues


async def test_quality_flags_axes_that_are_not_perpendicular() -> None:
    skew = np.array([[0.03, 0.03 * math.cos(math.radians(60))], [0.0, 0.03 * math.sin(math.radians(60))]])
    cal = await run(Rig(matrix=skew))
    assert "not_perpendicular" in cal.quality.issues
    assert cal.quality.axes_angle_deg == pytest.approx(60, abs=1)


# --- the same calibration at another pointing ---

CAL = Calibration(ra_x=0.02, ra_y=0.0, dec_x=0.0, dec_y=0.03, dec=0.0, pier_side="West")


def test_ra_speed_follows_the_declination() -> None:
    at60 = CAL.for_pointing(60.0, "West", flip_dec=False)
    assert at60.ra_x == pytest.approx(0.01) and at60.dec_y == pytest.approx(0.03)


def test_the_compensation_stops_near_the_pole() -> None:
    at89 = CAL.for_pointing(89.0, "West", flip_dec=False)
    assert at89.ra_x == pytest.approx(0.02 * math.cos(math.radians(75)))


def test_a_meridian_flip_reverses_ra_and_optionally_dec() -> None:
    motor = CAL.for_pointing(0.0, "East", flip_dec=False)
    assert (motor.ra_x, motor.dec_y) == pytest.approx((-0.02, 0.03))
    sky = CAL.for_pointing(0.0, "East", flip_dec=True)
    assert (sky.ra_x, sky.dec_y) == pytest.approx((-0.02, -0.03))


def test_unknown_pointing_leaves_the_calibration_alone() -> None:
    assert CAL.for_pointing(None, None, flip_dec=True) is CAL
    unknown = CAL.model_copy(update={"dec": None, "pier_side": None})
    assert unknown.for_pointing(40.0, "East", flip_dec=True).matrix.tolist() == unknown.matrix.tolist()
