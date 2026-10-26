"""Alpaca focuser adapter — implements IFocuser (absolute or relative focusers)."""
from __future__ import annotations

from typing import Any

import structlog

from astrolol.plugins.alpaca.base import AlpacaDevice
from astrolol.plugins.alpaca.client import AlpacaError
from astrolol.devices.base.models import DeviceState, FocuserStatus

logger = structlog.get_logger()

MOVE_TIMEOUT = 300.0


class AlpacaFocuser(AlpacaDevice):
    """IFocuser backed by an Alpaca Focuser device.

    A relative focuser has no position: it can only be moved by a number of steps.
    """

    ADAPTER_KEY = "alpaca_focuser"
    DEVICE_TYPE = "focuser"
    DEFAULT_CONNECT_PARAMS = dict(AlpacaDevice.DEFAULT_CONNECT_PARAMS)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._absolute = True
        self._max_step: int | None = None
        self._max_increment: int | None = None

    async def _on_connected(self) -> None:
        a = self._alpaca
        self._absolute = bool(await a.get_or("absolute", True))
        max_step = await a.get_or("maxstep", None)
        max_increment = await a.get_or("maxincrement", None)
        self._max_step = int(max_step) if max_step is not None else None
        self._max_increment = int(max_increment) if max_increment is not None else None

    async def move_to(self, position: int) -> None:
        if not self._absolute:
            raise ValueError("This focuser can only be moved by a number of steps")
        if position < 0 or (self._max_step is not None and position > self._max_step):
            raise ValueError(f"Position {position} is outside 0..{self._max_step}")
        await self._move(position)

    async def move_by(self, steps: int) -> None:
        if self._absolute:
            current = int(await self._alpaca.get("position"))
            await self.move_to(current + steps)
            return
        if self._max_increment is not None and abs(steps) > self._max_increment:
            raise ValueError(f"At most {self._max_increment} steps at a time")
        await self._move(steps)

    async def _move(self, value: int) -> None:
        self._state = DeviceState.BUSY
        try:
            await self._alpaca.put("move", Position=int(value))
            await self._wait_until(self._stopped, MOVE_TIMEOUT, "focuser move", interval=0.2)
        finally:
            self._state = DeviceState.CONNECTED

    async def _stopped(self) -> bool:
        return not await self._alpaca.get("ismoving")

    async def halt(self) -> None:
        try:
            await self._alpaca.put("halt")
        except AlpacaError as exc:
            logger.warning("alpaca.focuser_halt_failed", device=repr(self._alpaca), error=str(exc))

    async def get_status(self) -> FocuserStatus:
        a = self._alpaca
        if self._state not in (DeviceState.CONNECTED, DeviceState.BUSY):
            return FocuserStatus(state=self._state)
        position = await a.get_or("position", None) if self._absolute else None
        return FocuserStatus(
            state=self._state,
            position=int(position) if position is not None else None,
            is_moving=bool(await a.get_or("ismoving", False)),
            temperature=await a.get_or("temperature", None),
        )
