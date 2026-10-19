"""IndiMount works out LST, alt/az and hour angle itself when the driver does not publish them."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from astrolol.devices.indi.mount import IndiMount
from astrolol.mount.sky import alt_az, local_sidereal_time_h

LAT, LON = 50.6767, 3.9733


class _FakeClient:
    """Just the non-blocking readers get_status() uses; properties absent unless given."""

    def __init__(self, numbers: dict[tuple[str, str], float]) -> None:
        self._numbers = numbers

    def get_number_nowait(self, device: str, prop: str, element: str) -> float | None:
        return self._numbers.get((prop, element))

    def get_switch_state_nowait(self, device: str, prop: str, element: str) -> bool | None:
        return None

    def _get_vector(self, device: str, prop: str) -> None:
        return None


def _mount(numbers: dict[tuple[str, str], float]) -> IndiMount:
    return IndiMount(device_name="Telescope Simulator", client=_FakeClient(numbers))  # type: ignore[arg-type]


_POINTING = {("EQUATORIAL_EOD_COORD", "RA"): 5.5, ("EQUATORIAL_EOD_COORD", "DEC"): 10.0}
_SITE = {("GEOGRAPHIC_COORD", "LAT"): LAT, ("GEOGRAPHIC_COORD", "LONG"): LON}


@pytest.mark.asyncio
async def test_sky_position_is_computed_from_the_drivers_site() -> None:
    status = await _mount({**_POINTING, **_SITE}).get_status()
    assert status.lst is not None
    expected_lst = local_sidereal_time_h(datetime.now(timezone.utc), LON)
    assert status.lst == pytest.approx(expected_lst, abs=0.01)
    assert status.hour_angle == pytest.approx(((status.lst - 5.5 + 12) % 24) - 12)
    alt, az = alt_az(status.hour_angle, 10.0, LAT)
    assert status.alt == pytest.approx(alt, abs=0.2)
    assert status.az == pytest.approx(az, abs=0.2)


@pytest.mark.asyncio
async def test_driver_values_win_over_the_computed_ones() -> None:
    numbers = {
        **_POINTING, **_SITE,
        ("TIME_LST", "LST"): 7.0,
        ("HORIZONTAL_COORD", "ALT"): 33.0,
        ("HORIZONTAL_COORD", "AZ"): 123.0,
    }
    status = await _mount(numbers).get_status()
    assert (status.lst, status.alt, status.az) == (7.0, 33.0, 123.0)
    assert status.hour_angle == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_only_the_missing_value_is_computed() -> None:
    status = await _mount({**_POINTING, **_SITE, ("TIME_LST", "LST"): 7.0}).get_status()
    assert status.lst == 7.0
    assert status.alt is not None and status.az is not None
    alt, az = alt_az(1.5, 10.0, LAT)
    assert (status.alt, status.az) == (pytest.approx(alt), pytest.approx(az))


@pytest.mark.asyncio
async def test_nothing_is_invented_without_a_site() -> None:
    status = await _mount(_POINTING).get_status()
    assert (status.lst, status.alt, status.az, status.hour_angle) == (None, None, None, None)


@pytest.mark.asyncio
async def test_hour_angle_wraps_into_half_a_day() -> None:
    status = await _mount({**_POINTING, ("TIME_LST", "LST"): 23.5}).get_status()
    assert status.hour_angle == pytest.approx(-6.0)
