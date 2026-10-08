import pytest

from plugins.guider.calibration import Calibration
from plugins.guider.controller import AxisSettings, GuideController

CAL = Calibration(ra_x=0.01, ra_y=0.0, dec_x=0.0, dec_y=0.01, dec_backlash_ms=300)
FINE = AxisSettings(min_pulse_ms=5, aggressiveness=1.0, hysteresis=0.0, min_move_px=0.0)


def controller(**kw) -> GuideController:  # noqa: ANN003
    return GuideController(CAL, FINE, FINE, compensate_backlash=True, **kw)


def north_ms(pulses) -> int:  # noqa: ANN001
    return sum(ms if d == "N" else -ms for d, ms in pulses if d in "NS")


def test_a_reversal_gets_the_backlash_added() -> None:
    c = controller(last_dec_dir=1)  # last went North
    assert north_ms(c.correct(0.0, -1.0)) == 100  # star south of the lock: pulse North, same way
    assert north_ms(c.correct(0.0, 1.0)) == -(100 + 300)  # now the other way: South plus the slack
    assert north_ms(c.correct(0.0, 1.0)) == -100  # the slack is taken up: no more extra


def test_no_extra_when_the_direction_is_unknown_or_unchanged() -> None:
    c = controller(last_dec_dir=0)
    assert north_ms(c.correct(0.0, 1.0)) == -100


def test_after_calibration_the_last_dec_direction_is_south() -> None:
    c = controller(last_dec_dir=-1)
    assert north_ms(c.correct(0.0, -1.0)) == 100 + 300  # North reverses the calibration's South


def test_compensation_can_be_switched_off() -> None:
    c = GuideController(CAL, FINE, FINE, compensate_backlash=False, last_dec_dir=1)
    assert north_ms(c.correct(0.0, 1.0)) == -100


def test_ra_is_never_compensated() -> None:
    c = controller(last_dec_dir=1)
    c.calibration.ra_backlash_ms = 500
    west = [ms for d, ms in c.correct(-1.0, 0.0) if d == "W"]
    assert west == [100]


def test_compensation_is_capped_by_the_max_pulse() -> None:
    capped = AxisSettings(min_pulse_ms=5, aggressiveness=1.0, hysteresis=0.0, min_move_px=0.0, max_pulse_ms=150)
    c = GuideController(CAL, FINE, capped, compensate_backlash=True, last_dec_dir=1)
    assert north_ms(c.correct(0.0, 1.0)) == -(100 + 150)


def test_a_pulse_below_the_minimum_does_not_count_as_a_direction() -> None:
    # a 20 ms correction is under the 500 ms minimum, slack or not: nothing goes out, and the
    # direction is not considered to have changed
    coarse = AxisSettings(min_pulse_ms=500, aggressiveness=1.0, hysteresis=0.0, min_move_px=0.0)
    c = GuideController(CAL, FINE, coarse, compensate_backlash=True, last_dec_dir=1)
    assert c.correct(0.0, 0.2) == []
    assert c._dec_dir == 1
