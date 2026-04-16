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
        # busy_timeout=1s: drivers acknowledge within a fraction of a second;
        # done_timeout=120s: real mounts can take up to two minutes to reach park.
        await self._client.wait_prop_busy_then_done(
            self._device_name, "TELESCOPE_PARK", busy_timeout=1.0, done_timeout=120.0
        )
        self._is_parked = True
        self._is_tracking = False

    async def unpark(self) -> None:
        await self._client.set_switch(self._device_name, "TELESCOPE_PARK", ["UNPARK"])
        await self._client.wait_prop_busy_then_done(
            self._device_name, "TELESCOPE_PARK", busy_timeout=1.0, done_timeout=120.0
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
        # Required properties — wait briefly for them to arrive after connect.
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

        tracking = self._client.get_switch_state_nowait(
            self._device_name, "TELESCOPE_TRACK_STATE", "TRACK_ON"
        )
        if tracking is not None:
            self._is_tracking = tracking

        park_v = self._client._get_vector(self._device_name, "TELESCOPE_PARK")
        if park_v is not None and park_v.state != "Busy":
            parked = self._client.get_switch_state_nowait(
                self._device_name, "TELESCOPE_PARK", "PARK"
            )
            if parked is not None:
                self._is_parked = parked

        # Optional properties — read non-blocking; absent on some drivers.
        pier_side: str | None = None
        pier_east = self._client.get_switch_state_nowait(
            self._device_name, "TELESCOPE_PIER_SIDE", "PIER_EAST"
        )
        if pier_east is not None:
            pier_side = "East" if pier_east else "West"

        hour_angle: float | None = None
        lst: float | None = None
        lst = self._client.get_number_nowait(self._device_name, "TIME_LST", "LST")
        if ra is not None and lst is not None:
            ha = lst - ra
            while ha > 12:
                ha -= 24
            while ha < -12:
                ha += 24
            hour_angle = ha

        alt = self._client.get_number_nowait(self._device_name, "HORIZONTAL_COORD", "ALT")
        az  = self._client.get_number_nowait(self._device_name, "HORIZONTAL_COORD", "AZ")

        v = self._client._get_vector(self._device_name, "EQUATORIAL_EOD_COORD")
        is_slewing = v is not None and v.state == "Busy"

        return MountStatus(
            state=self._state,
            ra=ra,
            dec=dec,
            alt=alt,
            az=az,
            is_tracking=self._is_tracking,
            is_parked=self._is_parked,
            is_slewing=is_slewing,
            pier_side=pier_side,
            hour_angle=hour_angle,
            lst=lst,
        )

    async def set_park_position(self) -> None:
        """Set the current position as the park position and persist it to disk.

        INDI requires two steps:
          1. PARK_CURRENT — tells the driver to use the current position as park.
          2. PARK_WRITE_DATA — writes the park data to the driver's park file
             (e.g. ~/.indi/ParkData.xml for EQMod) so it survives a driver restart.
        """
        await self._client.set_switch(
            self._device_name, "TELESCOPE_PARK_OPTION", ["PARK_CURRENT"]
        )
        try:
            await self._client.set_switch(
                self._device_name, "TELESCOPE_PARK_OPTION", ["PARK_WRITE_DATA"]
            )
            logger.info("indi.park_position_saved", device=self._device_name)
        except Exception as exc:
            # PARK_WRITE_DATA is not present in all drivers — treat as best-effort.
            logger.warning(
                "indi.park_write_data_failed",
                device=self._device_name, error=str(exc),
            )

    _SLEW_RATE_ELEMENTS = {
        "guide":     "SLEW_GUIDE",
        "centering": "SLEW_CENTERING",
        "find":      "SLEW_FIND",
        "max":       "SLEW_MAX",
    }

    async def start_move(self, direction: str, rate: str) -> None:
        """Start continuous motion. Call stop_move() to halt.

        direction: "N" | "S" | "E" | "W"
        rate:      "guide" | "centering" | "find" | "max"
        """
        indi_rate = self._SLEW_RATE_ELEMENTS.get(rate, "SLEW_CENTERING")
        try:
            await self._client.set_switch(self._device_name, "TELESCOPE_SLEW_RATE", [indi_rate])
        except Exception:
            pass  # not all drivers expose a writable slew rate

        if direction in ("N", "S"):
            element = "MOTION_NORTH" if direction == "N" else "MOTION_SOUTH"
            await self._client.set_switch(self._device_name, "TELESCOPE_MOTION_NS", [element])
        elif direction in ("E", "W"):
            element = "MOTION_EAST" if direction == "E" else "MOTION_WEST"
            await self._client.set_switch(self._device_name, "TELESCOPE_MOTION_WE", [element])

    async def stop_move(self) -> None:
        """Stop all directional motion."""
        import asyncio as _asyncio
        for prop in ("TELESCOPE_MOTION_NS", "TELESCOPE_MOTION_WE"):
            try:
                await _asyncio.wait_for(
                    self._client.set_switch(self._device_name, prop, []),
                    timeout=2.0,
                )
            except Exception:
                pass

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

    async def set_location(self, lat: float, lon: float, alt: float) -> None:
        """Push geographic coordinates to the driver (GEOGRAPHIC_COORD).

        Required for accurate GoTo, meridian-flip window, and alt/az display.
        Best-effort: silently ignored if the driver does not expose GEOGRAPHIC_COORD.
        """
        await self._client.set_number(
            self._device_name,
            "GEOGRAPHIC_COORD",
            {"LAT": lat, "LONG": lon, "ELEV": alt},
        )
        logger.info("indi.mount_location_set", device=self._device_name, lat=lat, lon=lon, alt=alt)

    async def set_time_utc(self) -> None:
        """Push current UTC time and local UTC offset to the driver (TIME_UTC).

        Required for accurate sidereal-time computation, GoTo, and tracking.
        The UTC offset is informational (drivers use UTC for all math) but
        sent for completeness so the driver's local-time display is correct.
        """
        import datetime
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        local_offset = datetime.datetime.now().astimezone().utcoffset()
        offset_hours = local_offset.total_seconds() / 3600.0 if local_offset else 0.0
        await self._client.set_text(
            self._device_name,
            "TIME_UTC",
            {
                "UTC": utc_now.strftime("%Y-%m-%dT%H:%M:%S"),
                "OFFSET": str(offset_hours),
            },
        )
        logger.info("indi.mount_time_set", device=self._device_name, utc=utc_now.isoformat())

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
