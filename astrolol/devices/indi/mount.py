"""
INDI mount adapter — implements IMount using IndiClient.

INDI telescope properties used:
  EQUATORIAL_EOD_COORD  NUMBER  RA, DEC   — current position / slew target
  ON_COORD_SET          SWITCH  SLEW / TRACK / SYNC
  TELESCOPE_MOTION_NS   SWITCH  (for abort — we set EQUATORIAL_EOD_COORD again)
  TELESCOPE_ABORT_MOTION SWITCH ABORT_MOTION
  TELESCOPE_PARK        SWITCH  PARK / UNPARK
  TELESCOPE_TRACK_STATE SWITCH  TRACK_ON / TRACK_OFF
  TELESCOPE_INFO        NUMBER  — info block (used for ping)
"""
from __future__ import annotations

import structlog

from astrolol.devices.base.models import (
    DeviceState,
    MountStatus,
    SlewTarget,
)
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()


class IndiMount:
    """IMount implementation backed by an INDI Telescope driver."""

    ADAPTER_KEY = "indi_mount"

    def __init__(self, device_name: str, client: IndiClient) -> None:
        self._device_name = device_name
        self._client = client
        self._state = DeviceState.DISCONNECTED
        self._is_parked = False
        self._is_tracking = False

    # ------------------------------------------------------------------
    # IMount protocol
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

    async def slew(self, target: SlewTarget) -> None:
        """Slew to target and block until motion stops."""
        # Set ON_COORD_SET to TRACK (slew then start tracking)
        await self._client.set_switch(
            self._device_name, "ON_COORD_SET", ["TRACK"]
        )
        await self._client.set_number(
            self._device_name,
            "EQUATORIAL_EOD_COORD",
            {"RA": target.ra, "DEC": target.dec},
        )
        # Wait for mount to finish slewing by polling TELESCOPE_SLEWING
        await self._wait_slew_done()
        self._is_tracking = True

    async def stop(self) -> None:
        try:
            await self._client.set_switch(
                self._device_name, "TELESCOPE_ABORT_MOTION", ["ABORT_MOTION"]
            )
        except Exception as exc:
            logger.warning("indi.mount_stop_failed", device=self._device_name, error=str(exc))

    async def park(self) -> None:
        await self._client.set_switch(self._device_name, "TELESCOPE_PARK", ["PARK"])
        self._is_parked = True
        self._is_tracking = False

    async def unpark(self) -> None:
        await self._client.set_switch(self._device_name, "TELESCOPE_PARK", ["UNPARK"])
        self._is_parked = False

    async def sync(self, target: SlewTarget) -> None:
        await self._client.set_switch(self._device_name, "ON_COORD_SET", ["SYNC"])
        await self._client.set_number(
            self._device_name,
            "EQUATORIAL_EOD_COORD",
            {"RA": target.ra, "DEC": target.dec},
        )

    async def set_tracking(self, enabled: bool) -> None:
        element = "TRACK_ON" if enabled else "TRACK_OFF"
        await self._client.set_switch(
            self._device_name, "TELESCOPE_TRACK_STATE", [element]
        )
        self._is_tracking = enabled

    async def get_status(self) -> MountStatus:
        ra: float | None = None
        dec: float | None = None

        try:
            ra = await self._client.get_number(
                self._device_name, "EQUATORIAL_EOD_COORD", "RA"
            )
            dec = await self._client.get_number(
                self._device_name, "EQUATORIAL_EOD_COORD", "DEC"
            )
        except Exception:
            pass

        try:
            self._is_tracking = await self._client.get_switch_state(
                self._device_name, "TELESCOPE_TRACK_STATE", "TRACK_ON"
            )
        except Exception:
            pass

        try:
            self._is_parked = await self._client.get_switch_state(
                self._device_name, "TELESCOPE_PARK", "PARK"
            )
        except Exception:
            pass

        return MountStatus(
            state=self._state,
            ra=ra,
            dec=dec,
            is_tracking=self._is_tracking,
            is_parked=self._is_parked,
            is_slewing=False,  # derived from INDI state but we keep it simple
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

    async def _wait_slew_done(self, timeout: float = 120.0) -> None:
        """Wait until EQUATORIAL_EOD_COORD leaves IPS_BUSY."""
        await self._client.wait_prop_not_busy(
            self._device_name, "EQUATORIAL_EOD_COORD", timeout=timeout
        )
