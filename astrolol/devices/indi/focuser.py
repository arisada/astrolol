"""
INDI focuser adapter — implements IFocuser using IndiClient.

INDI focuser properties used:
  ABS_FOCUS_POSITION  NUMBER  FOCUS_ABSOLUTE_POSITION  — absolute move / current position
  FOCUS_ABORT_MOTION  SWITCH  ABORT                    — halt
  FOCUS_TEMPERATURE   NUMBER  TEMPERATURE              — optional
"""
from __future__ import annotations

import structlog

from astrolol.devices.base.models import DeviceState, FocuserStatus
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()

_MOVE_TIMEOUT = 60.0        # maximum time for any move


class IndiFocuser:
    """IFocuser implementation backed by an INDI Focuser driver."""

    ADAPTER_KEY = "indi_focuser"

    def __init__(self, device_name: str, client: IndiClient, pre_connect_props: dict | None = None) -> None:
        self._device_name = device_name
        self._client = client
        self._pre_connect_props = pre_connect_props
        self._state = DeviceState.DISCONNECTED

    # ------------------------------------------------------------------
    # IFocuser protocol
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._state = DeviceState.CONNECTING
        try:
            await self._client.connect_device(
                self._device_name,
                pre_connect_props=self._pre_connect_props,
            )
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
        """Move focuser by relative steps (positive = outward, negative = inward).

        Implemented via an absolute move to avoid a bug in the INDI focuser
        simulator where INWARD relative moves go BUSY and never complete.
        """
        self._state = DeviceState.BUSY
        try:
            current = await self._client.get_number(
                self._device_name, "ABS_FOCUS_POSITION", "FOCUS_ABSOLUTE_POSITION"
            )
            target = max(0, int(current) + steps)
            await self._client.set_number(
                self._device_name,
                "ABS_FOCUS_POSITION",
                {"FOCUS_ABSOLUTE_POSITION": float(target)},
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

    async def _wait_move_done(self, busy_timeout: float = 2.0) -> None:
        """Wait for ABS_FOCUS_POSITION to go BUSY then return to idle."""
        await self._client.wait_prop_busy_then_done(
            self._device_name,
            "ABS_FOCUS_POSITION",
            busy_timeout=busy_timeout,
            done_timeout=_MOVE_TIMEOUT,
        )
