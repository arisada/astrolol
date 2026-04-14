"""
INDI mount adapter — implements IMount using IndiClient.

INDI telescope properties used:
  EQUATORIAL_EOD_COORD  NUMBER  RA, DEC   — current position / slew target
  ON_COORD_SET          SWITCH  SLEW / TRACK / SYNC
  TELESCOPE_ABORT_MOTION SWITCH ABORT_MOTION
  TELESCOPE_PARK        SWITCH  PARK / UNPARK
  TELESCOPE_TRACK_STATE SWITCH  TRACK_ON / TRACK_OFF
  TELESCOPE_TRACK_RATE  SWITCH  TRACK_SIDEREAL / TRACK_LUNAR / TRACK_SOLAR
  TELESCOPE_PIER_SIDE   SWITCH  PIER_EAST / PIER_WEST  (read; write triggers flip on EQMod)
  TIME_LST              NUMBER  LST  — used to derive hour angle when no direct HA property
  TELESCOPE_INFO        NUMBER  — info block (used for ping)
"""
from __future__ import annotations

import structlog

from astrolol.devices.base.models import (
    DeviceState,
    MountStatus,
    SlewTarget,
    TrackingMode,
)
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()


class IndiMount:
    """IMount implementation backed by an INDI Telescope driver."""

    ADAPTER_KEY = "indi_mount"

    def __init__(self, device_name: str, client: IndiClient, pre_connect_props: dict | None = None) -> None:
        self._device_name = device_name
        self._client = client
        self._pre_connect_props = pre_connect_props
        self._state = DeviceState.DISCONNECTED
        self._is_parked = False
        self._is_tracking = False

    # ------------------------------------------------------------------
    # IMount protocol
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

    async def slew(self, target: SlewTarget) -> None:
        """Slew to target and block until motion stops."""
        # Unpark first — INDI telescope simulators (and most real drivers) ignore
        # slew commands when the mount is in a parked state.
        try:
            is_parked = await self._client.get_switch_state(
                self._device_name, "TELESCOPE_PARK", "PARK"
            )
            if is_parked:
                await self.unpark()
        except Exception:
            pass
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
        # Wait for TELESCOPE_PARK to go BUSY then return to OK.
        # busy_timeout=5s gives the driver time to acknowledge the command.
        await self._client.wait_prop_busy_then_done(
            self._device_name, "TELESCOPE_PARK", busy_timeout=5.0, done_timeout=120.0
        )
        self._is_parked = True
        self._is_tracking = False

    async def unpark(self) -> None:
        await self._client.set_switch(self._device_name, "TELESCOPE_PARK", ["UNPARK"])
        await self._client.wait_prop_busy_then_done(
            self._device_name, "TELESCOPE_PARK", busy_timeout=5.0, done_timeout=120.0
        )
        self._is_parked = False

    async def sync(self, target: SlewTarget) -> None:
        await self._client.set_switch(self._device_name, "ON_COORD_SET", ["SYNC"])
        await self._client.set_number(
            self._device_name,
            "EQUATORIAL_EOD_COORD",
            {"RA": target.ra, "DEC": target.dec},
        )

    _TRACK_RATE_ELEMENTS = {
        TrackingMode.SIDEREAL: "TRACK_SIDEREAL",
        TrackingMode.LUNAR:    "TRACK_LUNAR",
        TrackingMode.SOLAR:    "TRACK_SOLAR",
    }

    async def set_tracking(self, enabled: bool, mode: TrackingMode | None = None) -> None:
        # Set rate first so the driver has the right mode when tracking is enabled
        if enabled and mode is not None:
            rate_element = self._TRACK_RATE_ELEMENTS.get(mode)
            if rate_element:
                try:
                    await self._client.set_switch(
                        self._device_name, "TELESCOPE_TRACK_RATE", [rate_element]
                    )
                except Exception as exc:
                    logger.debug(
                        "indi.mount_track_rate_skipped",
                        device=self._device_name,
                        mode=mode,
                        error=str(exc),
                    )
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

        pier_side: str | None = None
        try:
            pier_east = await self._client.get_switch_state(
                self._device_name, "TELESCOPE_PIER_SIDE", "PIER_EAST"
            )
            pier_side = "East" if pier_east else "West"
        except Exception:
            pass

        hour_angle: float | None = None
        try:
            lst = await self._client.get_number(
                self._device_name, "TIME_LST", "LST"
            )
            if ra is not None and lst is not None:
                ha = lst - ra
                # Normalize to -12..+12
                while ha > 12:
                    ha -= 24
                while ha < -12:
                    ha += 24
                hour_angle = ha
        except Exception:
            pass

        return MountStatus(
            state=self._state,
            ra=ra,
            dec=dec,
            is_tracking=self._is_tracking,
            is_parked=self._is_parked,
            is_slewing=False,  # derived from INDI state but we keep it simple
            pier_side=pier_side,
            hour_angle=hour_angle,
        )

    async def meridian_flip(self) -> None:
        """Slew to the current target on the opposite pier side (meridian flip).

        Sets TELESCOPE_PIER_SIDE to the opposite before issuing the slew so that
        EQMod (and other drivers that support writable pier side) will approach
        from the correct direction.  On read-only drivers the set is a no-op and
        the slew re-centres in place — harmless, just not a true flip.
        """
        ra = await self._client.get_number(
            self._device_name, "EQUATORIAL_EOD_COORD", "RA"
        )
        dec = await self._client.get_number(
            self._device_name, "EQUATORIAL_EOD_COORD", "DEC"
        )

        # Request opposite pier side (best-effort — ignored on read-only drivers)
        try:
            pier_east = await self._client.get_switch_state(
                self._device_name, "TELESCOPE_PIER_SIDE", "PIER_EAST"
            )
            target_side = "PIER_WEST" if pier_east else "PIER_EAST"
            await self._client.set_switch(
                self._device_name, "TELESCOPE_PIER_SIDE", [target_side]
            )
        except Exception:
            pass

        await self._client.set_switch(self._device_name, "ON_COORD_SET", ["TRACK"])
        await self._client.set_number(
            self._device_name,
            "EQUATORIAL_EOD_COORD",
            {"RA": ra, "DEC": dec},
        )
        await self._wait_slew_done()
        self._is_tracking = True

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
        """Wait for EQUATORIAL_EOD_COORD to go BUSY then return to idle."""
        await self._client.wait_prop_busy_then_done(
            self._device_name, "EQUATORIAL_EOD_COORD", done_timeout=timeout
        )
