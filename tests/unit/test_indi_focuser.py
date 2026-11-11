"""IndiFocuser: a move that ends a few steps short is asked again, once."""
from __future__ import annotations

import logging

import pytest

from astrolol.devices.indi.focuser import IndiFocuser


class FakeClient:
    """Stops `short` steps before the target on the first `short_moves` moves, then lands exactly."""

    def __init__(self, short: int = 0, short_moves: int = 0) -> None:
        self.position = 1000.0
        self.short = short
        self.short_moves = short_moves
        self.requests: list[float] = []

    async def set_number(self, device: str, prop: str, values: dict[str, float]) -> None:
        target = values["FOCUS_ABSOLUTE_POSITION"]
        self.requests.append(target)
        if self.short_moves > 0:
            self.short_moves -= 1
            self.position = target - self.short
        else:
            self.position = target

    async def get_number(self, device: str, prop: str, element: str) -> float:
        return self.position

    async def wait_prop_busy_then_done(self, *args: object, **kwargs: object) -> None:
        return None


async def test_a_move_that_lands_on_target_is_one_request() -> None:
    client = FakeClient()
    await IndiFocuser("foc", client).move_to(1500)  # type: ignore[arg-type]
    assert client.requests == [1500.0]


async def test_a_move_short_of_the_target_is_asked_again() -> None:
    client = FakeClient(short=6, short_moves=1)
    await IndiFocuser("foc", client).move_to(1500)  # type: ignore[arg-type]
    assert client.requests == [1500.0, 1500.0]
    assert client.position == 1500


async def test_a_focuser_that_stays_short_is_asked_once_more_then_logged(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient(short=6, short_moves=10)
    with caplog.at_level(logging.WARNING, logger="astrolol.devices.indi.focuser"):
        await IndiFocuser("foc", client).move_to(1500)  # type: ignore[arg-type]
    assert client.requests == [1500.0, 1500.0]  # no loop
    assert "indi.focuser_short_of_target" in caplog.text + capsys.readouterr().out


async def test_move_by_goes_through_the_same_check() -> None:
    client = FakeClient(short=4, short_moves=1)
    await IndiFocuser("foc", client).move_by(200)  # type: ignore[arg-type]
    assert client.requests == [1200.0, 1200.0]
