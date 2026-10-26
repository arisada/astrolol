"""Alpaca filter wheel adapter — implements IFilterWheel.

Alpaca counts slots from 0 and reports -1 while the wheel turns; astrolol counts from 1.
"""
from __future__ import annotations

from typing import Any

from astrolol.plugins.alpaca.base import AlpacaDevice
from astrolol.devices.base.models import DeviceState, FilterWheelStatus

MOVE_TIMEOUT = 60.0


class AlpacaFilterWheel(AlpacaDevice):
    """IFilterWheel backed by an Alpaca FilterWheel device."""

    ADAPTER_KEY = "alpaca_filter_wheel"
    DEVICE_TYPE = "filterwheel"
    DEFAULT_CONNECT_PARAMS = dict(AlpacaDevice.DEFAULT_CONNECT_PARAMS)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._names: list[str] = []

    async def _on_connected(self) -> None:
        self._names = [str(n) for n in (await self._alpaca.get("names") or [])]

    async def select_filter(self, slot: int) -> None:
        if not 1 <= slot <= len(self._names):
            raise ValueError(f"Slot {slot} is outside 1..{len(self._names)}")
        self._state = DeviceState.BUSY
        try:
            await self._alpaca.put("position", Position=slot - 1)
            await self._wait_until(self._arrived, MOVE_TIMEOUT, "filter change", interval=0.2)
        finally:
            self._state = DeviceState.CONNECTED

    async def _arrived(self) -> bool:
        return int(await self._alpaca.get("position")) != -1

    async def get_status(self) -> FilterWheelStatus:
        if self._state not in (DeviceState.CONNECTED, DeviceState.BUSY):
            return FilterWheelStatus(state=self._state)
        position = int(await self._alpaca.get("position"))
        return FilterWheelStatus(
            state=self._state,
            current_slot=position + 1 if position >= 0 else None,
            filter_count=len(self._names),
            filter_names=self._names,
            is_moving=position == -1,
        )
