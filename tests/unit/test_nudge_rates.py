import pytest

from astrolol.mount.rates import MAX_NUDGE_X_SIDEREAL, nudge_speed_x_sidereal


def test_names_keep_their_meaning() -> None:
    assert nudge_speed_x_sidereal("guide") == 0.5
    assert nudge_speed_x_sidereal("centering") == 16
    assert nudge_speed_x_sidereal("find") == 64
    assert nudge_speed_x_sidereal("max") == MAX_NUDGE_X_SIDEREAL == 800


@pytest.mark.parametrize("rate,x", [("1x", 1.0), ("16x", 16.0), ("0.5x", 0.5), ("800X", 800.0), (" 64x ", 64.0)])
def test_multipliers(rate: str, x: float) -> None:
    assert nudge_speed_x_sidereal(rate) == x


@pytest.mark.parametrize("rate", ["", "x", "fast", "0x", "800.5x", "1000x", "-1x", "16"])
def test_rejects(rate: str) -> None:
    with pytest.raises(ValueError):
        nudge_speed_x_sidereal(rate)
