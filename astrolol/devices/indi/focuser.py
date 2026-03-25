"""
INDI focuser adapter — implements IFocuser using IndiClient.

INDI focuser properties used:
  ABS_FOCUS_POSITION  NUMBER  FOCUS_ABSOLUTE_POSITION  — absolute move / current position
  REL_FOCUS_POSITION  NUMBER  FOCUS_RELATIVE_POSITION  — relative move
  FOCUS_MOTION        SWITCH  FOCUS_INWARD / FOCUS_OUTWARD — direction for relative move
  FOCUS_ABORT_MOTION  SWITCH  ABORT                        — halt
  FOCUS_TEMPERATURE   NUMBER  TEMPERATURE                  — optional
"""
from __future__ import annotations

import asyncio
import time

import structlog

from astrolol.devices.base.models import DeviceState, FocuserStatus
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()

_MOVE_POLL_INTERVAL = 0.3   # seconds between position polls
_MOVE_TIMEOUT = 60.0        # maximum time for any move


class IndiFocuser:
    """IFocuser implementation backed by an INDI Focuser driver."""

    ADAPTER_KEY = "indi_focuser"

    def __init__(self, device_name: str, client: IndiClient) -> None:
        self._device_name = device_name
        self._client = client
        self._state = DeviceState.DISCONNECTED

    # ------------------------------------------------------------------
    # IFocuser protocol
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._state = DeviceState.CONNECTING
        try:
            await self._client.connect_device(self._device_name)
            self._state = DeviceState.CONNECTED
        except Exception:
            self._state = DeviceState.ERROR
            raise

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect_device(self._device_name)
        finally:
            self._state = DeviceState.DISCONNECTED

    async def move_to(self, position: int) -> None:
        """Move focuser to absolute position and wait until done."""
        self._state = DeviceState.BUSY
        try:
            await self._client.set_number(
                self._device_name,
                "ABS_FOCUS_POSITION",
                {"FOCUS_ABSOLUTE_POSITION": float(position)},
            )
            await self._wait_move_done()
        finally:
            self._state = DeviceState.CONNECTED

    async def move_by(self, steps: int) -> None:
        """Move focuser by relative steps (positive = outward, negative = inward)."""
        self._state = DeviceState.BUSY
        try:
            direction = "FOCUS_OUTWARD" if steps >= 0 else "FOCUS_INWARD"
            await self._client.set_switch(
                self._device_name, "FOCUS_MOTION", [direction]
            )
            await self._client.set_number(
                self._device_name,
                "REL_FOCUS_POSITION",
                {"FOCUS_RELATIVE_POSITION": float(abs(steps))},
            )
            await self._wait_move_done()
        finally:
            self._state = DeviceState.CONNECTED

    async def halt(self) -> None:
        try:
            await self._client.set_switch(
                self._device_name, "FOCUS_ABORT_MOTION", ["ABORT"]
            )
        except Exception as exc:
            logger.warning(
                "indi.focuser_halt_failed", device=self._device_name, error=str(exc)
            )
        finally:
            self._state = DeviceState.CONNECTED

    async def get_status(self) -> FocuserStatus:
        position: int | None = None
        temperature: float | None = None

        try:
            pos = await self._client.get_number(
                self._device_name, "ABS_FOCUS_POSITION", "FOCUS_ABSOLUTE_POSITION"
            )
            position = int(pos)
        except Exception:
            pass

        try:
            temperature = await self._client.get_number(
                self._device_name, "FOCUS_TEMPERATURE", "TEMPERATURE"
            )
        except Exception:
            pass

        return FocuserStatus(
            state=self._state,
            position=position,
            is_moving=(self._state == DeviceState.BUSY),
            temperature=temperature,
        )

    async def ping(self) -> bool:
        try:
            await self._client.wait_for_property(
                self._device_name, "CONNECTION", timeout=3.0
            )
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _wait_move_done(self) -> None:
        """Poll ABS_FOCUS_POSITION state until it leaves BUSY."""
        deadline = time.monotonic() + _MOVE_TIMEOUT
        while True:
            try:
                prop = await self._client.wait_for_property(
                    self._device_name, "ABS_FOCUS_POSITION", timeout=3.0
                )
                if prop.getState() != 1:  # not IPS_BUSY
                    return
            except Exception:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("Focuser move did not complete within timeout")
            await asyncio.sleep(_MOVE_POLL_INTERVAL)
