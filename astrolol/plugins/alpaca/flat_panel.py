"""Alpaca cover calibrator adapter — implements IFlatPanel (dust cover and/or light panel)."""
from __future__ import annotations

from typing import Any

import structlog

from astrolol.plugins.alpaca.base import AlpacaDevice
from astrolol.devices.base.models import CoverState, DeviceState, FlatPanelStatus

logger = structlog.get_logger()

COVER_TIMEOUT = 120.0
LIGHT_TIMEOUT = 60.0

# CoverStatus: 0 not present, 1 closed, 2 moving, 3 open, 4 unknown, 5 error
_NO_COVER, _CLOSED, _MOVING, _OPEN = 0, 1, 2, 3
_COVER_STATES = {_CLOSED: CoverState.CLOSED, _MOVING: CoverState.MOVING, _OPEN: CoverState.OPEN}
# CalibratorStatus: 0 not present, 1 off, 2 not ready, 3 ready, 4 unknown, 5 error
_NO_LIGHT, _LIGHT_OFF, _LIGHT_NOT_READY, _LIGHT_READY = 0, 1, 2, 3


class AlpacaFlatPanel(AlpacaDevice):
    """IFlatPanel backed by an Alpaca CoverCalibrator device."""

    ADAPTER_KEY = "alpaca_flat_panel"
    DEVICE_TYPE = "covercalibrator"
    DEFAULT_CONNECT_PARAMS = dict(AlpacaDevice.DEFAULT_CONNECT_PARAMS)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._has_cover = False
        self._has_light = False
        self._max_brightness: int | None = None

    async def _on_connected(self) -> None:
        a = self._alpaca
        self._has_cover = int(await a.get("coverstate")) != _NO_COVER
        self._has_light = int(await a.get("calibratorstate")) != _NO_LIGHT
        if self._has_light:
            self._max_brightness = int(await a.get("maxbrightness"))

    async def open_cover(self) -> None:
        await self._move_cover("opencover", _OPEN)

    async def close_cover(self) -> None:
        await self._move_cover("closecover", _CLOSED)

    async def _move_cover(self, method: str, target: int) -> None:
        if not self._has_cover:
            raise ValueError("This device has no cover.")
        await self._alpaca.put(method)

        async def arrived() -> bool:
            state = int(await self._alpaca.get("coverstate"))
            if state not in (target, _MOVING):
                raise RuntimeError(f"cover stopped in state {state}")
            return state == target
        await self._wait_until(arrived, COVER_TIMEOUT, method, interval=0.5)

    async def set_light(self, on: bool, brightness: int | None = None) -> None:
        if not self._has_light:
            raise ValueError("This device has no light.")
        a = self._alpaca
        if not on:
            await a.put("calibratoroff")

            async def off() -> bool:
                return int(await a.get("calibratorstate")) in (_LIGHT_OFF, _NO_LIGHT)
            await self._wait_until(off, LIGHT_TIMEOUT, "light off", interval=0.25)
            return
        level = self._max_brightness if brightness is None else brightness
        if level is None or not 0 <= level <= (self._max_brightness or level):
            raise ValueError(f"Brightness must be within 0..{self._max_brightness}")
        await a.put("calibratoron", Brightness=int(level))

        async def ready() -> bool:
            state = int(await a.get("calibratorstate"))
            if state not in (_LIGHT_READY, _LIGHT_NOT_READY):
                raise RuntimeError(f"light stopped in state {state}")
            return state == _LIGHT_READY
        await self._wait_until(ready, LIGHT_TIMEOUT, "light", interval=0.25)
        logger.info("alpaca.flat_panel_light", device=repr(a), on=on, brightness=level)

    async def get_status(self) -> FlatPanelStatus:
        if self._state not in (DeviceState.CONNECTED, DeviceState.BUSY):
            return FlatPanelStatus(state=self._state)
        a = self._alpaca
        cover = None
        if self._has_cover:
            cover = _COVER_STATES.get(int(await a.get("coverstate")), CoverState.UNKNOWN)
        light_on = brightness = None
        if self._has_light:
            state = int(await a.get("calibratorstate"))
            brightness = int(await a.get_or("brightness", 0))
            # Not ready: warming up (on) or cooling down after it was switched off (brightness 0).
            light_on = state == _LIGHT_READY or (state == _LIGHT_NOT_READY and brightness > 0)
        return FlatPanelStatus(
            state=self._state,
            has_cover=self._has_cover, cover=cover,
            has_light=self._has_light, light_on=light_on,
            brightness=brightness, max_brightness=self._max_brightness,
        )
