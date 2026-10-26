"""Alpaca rotator adapter — implements IRotator (position only, like the INDI one)."""
from __future__ import annotations

from astrolol.plugins.alpaca.base import AlpacaDevice
from astrolol.devices.base.models import DeviceState, RotatorStatus


class AlpacaRotator(AlpacaDevice):
    """IRotator backed by an Alpaca Rotator device."""

    ADAPTER_KEY = "alpaca_rotator"
    DEVICE_TYPE = "rotator"
    DEFAULT_CONNECT_PARAMS = dict(AlpacaDevice.DEFAULT_CONNECT_PARAMS)

    async def get_status(self) -> RotatorStatus:
        if self._state not in (DeviceState.CONNECTED, DeviceState.BUSY):
            return RotatorStatus(state=self._state)
        position = await self._alpaca.get_or("position", None)
        return RotatorStatus(
            state=self._state,
            position=float(position) if position is not None else None,
            is_moving=bool(await self._alpaca.get_or("ismoving", False)),
        )
