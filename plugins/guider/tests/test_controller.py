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


def _guide_plant(real_backlash_ms: float, assumed_ms: float, start_px: float, steps: int = 60) -> list[float]:
    """Dec error (px, +North) per frame for a plant with *real_backlash_ms* of slack, guided with a
    controller that believes in *assumed_ms*."""
    cal = Calibration(ra_x=0.01, ra_y=0.0, dec_x=0.0, dec_y=0.01, dec_backlash_ms=assumed_ms)
    s = AxisSettings(min_pulse_ms=5, aggressiveness=0.6, hysteresis=0.1, min_move_px=0.15)
    c = GuideController(cal, s, s, compensate_backlash=True, last_dec_dir=-1)
    err, slack, direction, history = start_px, 0.0, -1, []
    for _ in range(steps):
        history.append(err)
        for d, ms in c.correct(0.0, err):
            if d not in "NS":
                continue
            sign = 1 if d == "N" else -1
            if sign != direction:
                direction, slack = sign, real_backlash_ms
            take = min(slack, ms)
            slack -= take
            err += sign * (ms - take) * 0.01  # a North pulse moves the star North
    return history


@pytest.mark.parametrize("real", [0.0, 40.0])
def test_an_overestimated_backlash_does_not_make_dec_ring(real: float) -> None:
    history = _guide_plant(real, assumed_ms=80.0, start_px=-0.6)
    tail = history[-10:]
    assert max(abs(e) for e in tail) < 0.6
    flips = sum(1 for a, b in zip(tail, tail[1:]) if a * b < 0)
    assert flips <= 2  # not one reversal per frame


def test_the_share_of_backlash_shrinks_only_when_it_overshoots() -> None:
    cal = Calibration(ra_x=0.01, ra_y=0.0, dec_x=0.0, dec_y=0.01, dec_backlash_ms=100)
    c = GuideController(cal, FINE, FINE, compensate_backlash=True, last_dec_dir=1)
    c.correct(0.0, 1.0)   # reverses: carries the compensation
    c.correct(0.0, 1.0)   # the error is still on the same side: it was not too much
    assert c.backlash_share == 1.0
    c.reset()
    c.correct(0.0, -1.0)  # reverses again
    c.correct(0.0, 1.0)   # now the star is on the other side: overshoot
    assert c.backlash_share < 1.0


def _resisting(**kw: object) -> GuideController:
    cal = Calibration(ra_x=0.01, ra_y=0.0, dec_x=0.0, dec_y=0.01)
    dec = AxisSettings(min_pulse_ms=5, min_move_px=0.15, resist_switch=True, **kw)
    return GuideController(cal, FINE, dec)


def _dec(c: GuideController, err: float) -> str:
    return "".join(d for d, _ in c.correct(0.0, err) if d in "NS")


def test_dec_does_not_reverse_on_a_single_small_deflection() -> None:
    c = _resisting()
    assert _dec(c, 0.3) == "S"
    assert _dec(c, -0.3) == ""   # seeing, not drift
    assert _dec(c, 0.3) == "S"   # back on the old side: the vote starts over


def test_dec_reverses_after_three_frames_in_a_row() -> None:
    c = _resisting()
    _dec(c, 0.3)
    assert [_dec(c, -0.3) for _ in range(3)] == ["", "", "N"]


def test_a_large_error_reverses_dec_at_once_unless_fast_switch_is_off() -> None:
    c = _resisting()
    _dec(c, 0.3)
    assert _dec(c, -0.6) == "N"
    c = _resisting(fast_switch=False)
    _dec(c, 0.3)
    assert _dec(c, -0.6) == ""


def test_resisting_is_off_by_default() -> None:
    c = GuideController(Calibration(ra_x=0.01, ra_y=0.0, dec_x=0.0, dec_y=0.01), FINE, FINE)
    _dec(c, 0.3)
    assert _dec(c, -0.3) == "N"
