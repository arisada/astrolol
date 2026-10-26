"""
Alpaca telescope adapter — implements IMount (and pulse guiding through the mount).

Coordinates go to and from the mount in the system it declares (EquatorialSystem): JNow
(topocentric, most mounts and OmniSim) or J2000. Alpaca has no push events, so while
astrolol listens for the position the adapter reads it once a second.

Nudging uses MoveAxis in degrees per second: the RA axis turns the same way on either side of
the pier (positive = west), the Dec axis the other way once the mount has flipped.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import astropy.units as u
import structlog
from astropy.coordinates import FK4, FK5, SkyCoord
from astropy.time import Time

from astrolol.plugins.alpaca.base import AlpacaDevice
from astrolol.plugins.alpaca.client import AlpacaError
from astrolol.plugins.alpaca.pulse import alpaca_pulse_guide
from astrolol.devices.base.models import DeviceState, MountStatus, TrackingMode
from astrolol.devices.base.pulse import PulseDirection, PulseGuideNotSupported
from astrolol.mount.rates import nudge_speed_x_sidereal
from astrolol.mount.sky import icrs_to_jnow, jnow_to_icrs

logger = structlog.get_logger()

SIDEREAL_DEG_PER_SEC = 360.0 / 86164.0905
COORDS_INTERVAL = 1.0
SLEW_TIMEOUT = 300.0
PARK_TIMEOUT = 300.0

# EquatorialSystem: 0 other, 1 topocentric (JNow), 2 J2000, 3 J2050, 4 B1950
_JNOW, _J2000, _J2050, _B1950 = 1, 2, 3, 4
# DriveRates
_DRIVE_RATES = {TrackingMode.SIDEREAL: 0, TrackingMode.LUNAR: 1, TrackingMode.SOLAR: 2}
# PierSide: 0 east (pointing west, the normal side), 1 west, -1 unknown
_PIER_SIDES = {0: "East", 1: "West"}


def _wrap_hours(ha: float) -> float:
    return (ha + 12.0) % 24.0 - 12.0


class AlpacaMount(AlpacaDevice):
    """IMount backed by an Alpaca Telescope device."""

    ADAPTER_KEY = "alpaca_mount"
    DEVICE_TYPE = "telescope"
    DEFAULT_CONNECT_PARAMS = dict(AlpacaDevice.DEFAULT_CONNECT_PARAMS)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._caps: dict[str, Any] = {}
        self._system = _JNOW
        self._on_coords_cb: Callable[..., None] | None = None
        self._coords_task: asyncio.Task[None] | None = None

    async def _on_connected(self) -> None:
        a = self._alpaca
        self._system = int(await a.get_or("equatorialsystem", _JNOW))
        self._caps = {
            "slew_async": bool(await a.get_or("canslewasync", False)),
            "slew": bool(await a.get_or("canslew", True)),
            "sync": bool(await a.get_or("cansync", False)),
            "park": bool(await a.get_or("canpark", False)),
            "unpark": bool(await a.get_or("canunpark", False)),
            "set_park": bool(await a.get_or("cansetpark", False)),
            "set_tracking": bool(await a.get_or("cansettracking", False)),
            "set_pier_side": bool(await a.get_or("cansetpierside", False)),
            "pulse": bool(await a.get_or("canpulseguide", False)),
            "move_ra": bool(await a.get_or("canmoveaxis", False, Axis=0)),
            "move_dec": bool(await a.get_or("canmoveaxis", False, Axis=1)),
            "max_rate": await self._max_axis_rate(),
        }

    async def _max_axis_rate(self) -> float | None:
        try:
            rates = await self._alpaca.get("axisrates", Axis=0) or []
        except AlpacaError:
            return None
        maxima = [float(r.get("Maximum", 0)) for r in rates if isinstance(r, dict)]
        return max(maxima) if maxima else None

    async def _on_disconnecting(self) -> None:
        # A mount left moving by hand keeps going once nobody is connected to stop it.
        await self.stop_move()
        self._on_coords_cb = None
        task, self._coords_task = self._coords_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Coordinates
    # ------------------------------------------------------------------

    def _to_mount(self, coord: SkyCoord) -> tuple[float, float]:
        """(RA hours, Dec degrees) of *coord* in the mount's equatorial system."""
        if self._system == _J2000:
            icrs = coord.icrs
            return float(icrs.ra.hour), float(icrs.dec.deg)
        if self._system == _J2050:
            c = coord.transform_to(FK5(equinox=Time("J2050")))
            return float(c.ra.hour), float(c.dec.deg)
        if self._system == _B1950:
            c = coord.transform_to(FK4(equinox=Time("B1950")))
            return float(c.ra.hour), float(c.dec.deg)
        return icrs_to_jnow(coord, datetime.now(timezone.utc))

    def _from_mount(self, ra_h: float, dec_deg: float) -> SkyCoord | None:
        if not -90.0 <= dec_deg <= 90.0:
            return None
        if self._system == _J2000:
            return SkyCoord(ra=ra_h * u.hourangle, dec=dec_deg * u.deg, frame="icrs")
        if self._system == _J2050:
            return SkyCoord(ra=ra_h * u.hourangle, dec=dec_deg * u.deg, frame=FK5(equinox=Time("J2050"))).icrs
        if self._system == _B1950:
            return SkyCoord(ra=ra_h * u.hourangle, dec=dec_deg * u.deg, frame=FK4(equinox=Time("B1950"))).icrs
        return jnow_to_icrs(ra_h, dec_deg, datetime.now(timezone.utc))

    async def _read(self) -> dict[str, Any]:
        a = self._alpaca
        names = ("rightascension", "declination", "altitude", "azimuth", "tracking", "atpark",
                 "slewing", "sideofpier", "siderealtime")
        values = await asyncio.gather(*(a.get_or(n, None) for n in names))
        return dict(zip(names, values))

    async def get_status(self) -> MountStatus:
        if self._state not in (DeviceState.CONNECTED, DeviceState.BUSY):
            return MountStatus(state=self._state)
        return self._status(await self._read())

    def _status(self, v: dict[str, Any]) -> MountStatus:
        ra_m, dec_m = v["rightascension"], v["declination"]
        ra = dec = ra_jnow = dec_jnow = None
        if ra_m is not None and dec_m is not None:
            icrs = self._from_mount(float(ra_m), float(dec_m))
            if icrs is not None:
                ra, dec = float(icrs.ra.hour), float(icrs.dec.deg)
                if self._system == _JNOW:
                    ra_jnow, dec_jnow = float(ra_m), float(dec_m)
                else:
                    ra_jnow, dec_jnow = icrs_to_jnow(icrs, datetime.now(timezone.utc))
        lst = float(v["siderealtime"]) if v["siderealtime"] is not None else None
        hour_angle = _wrap_hours(lst - ra_jnow) if lst is not None and ra_jnow is not None else None
        return MountStatus(
            state=self._state,
            ra=ra, dec=dec, ra_jnow=ra_jnow, dec_jnow=dec_jnow,
            alt=v["altitude"], az=v["azimuth"],
            is_tracking=bool(v["tracking"]),
            is_parked=bool(v["atpark"]),
            is_slewing=bool(v["slewing"]),
            pier_side=_PIER_SIDES.get(v["sideofpier"]) if v["sideofpier"] is not None else None,
            hour_angle=hour_angle,
            lst=lst,
        )

    def set_coords_listener(self, cb: Callable[..., None] | None) -> None:
        """Duck-typed by DeviceManager (same contract as IndiMount): the position once a second."""
        self._on_coords_cb = cb
        if cb is not None and self._coords_task is None:
            self._coords_task = asyncio.get_running_loop().create_task(self._coords_pump())

    async def _coords_pump(self) -> None:
        while True:
            try:
                cb = self._on_coords_cb
                if cb is not None:
                    s = await self.get_status()
                    cb(s.ra, s.dec, s.ra_jnow, s.dec_jnow, s.alt, s.az, s.pier_side, s.hour_angle,
                       s.lst, s.is_tracking, s.is_parked)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("alpaca.mount_coords_failed", device=repr(self._alpaca), error=str(exc))
            await asyncio.sleep(COORDS_INTERVAL)

    # ------------------------------------------------------------------
    # IMount
    # ------------------------------------------------------------------

    async def slew(self, coord: SkyCoord) -> None:
        """Slew to *coord* (any frame) and track there; returns when the slew is over."""
        a = self._alpaca
        await self.stop_move()   # a mount moving by hand counts as slewing, and would not go
        if await a.get_or("atpark", False):
            await self.unpark()
        if self._caps.get("set_tracking"):
            await a.put("tracking", Tracking=True)
        await self._slew_to(*self._to_mount(coord))

    async def _slew_to(self, ra_h: float, dec_deg: float) -> None:
        a = self._alpaca
        try:
            if self._caps.get("slew_async") or not self._caps.get("slew"):
                await a.put("slewtocoordinatesasync", RightAscension=ra_h, Declination=dec_deg)
                await self._wait_until(self._not_slewing, SLEW_TIMEOUT, "slew", interval=0.5)
            else:
                await a.put("slewtocoordinates", RightAscension=ra_h, Declination=dec_deg, timeout=SLEW_TIMEOUT)
        except asyncio.CancelledError:
            await self.stop()
            raise

    async def _not_slewing(self) -> bool:
        return not await self._alpaca.get("slewing")

    async def stop(self) -> None:
        a = self._alpaca
        try:
            await a.put("abortslew")
        except AlpacaError as exc:
            logger.warning("alpaca.mount_stop_failed", device=repr(a), error=str(exc))
        await self.stop_move()

    async def park(self) -> None:
        if not self._caps.get("park"):
            raise ValueError("This mount cannot park")
        await self._alpaca.put("park", timeout=PARK_TIMEOUT)
        await self._wait_until(self._parked, PARK_TIMEOUT, "park", interval=0.5)

    async def _parked(self) -> bool:
        return bool(await self._alpaca.get("atpark"))

    async def unpark(self) -> None:
        if self._caps.get("unpark"):
            await self._alpaca.put("unpark", timeout=PARK_TIMEOUT)
            await self._wait_until(self._unparked, PARK_TIMEOUT, "unpark", interval=0.5)

    async def _unparked(self) -> bool:
        return not await self._alpaca.get("atpark")

    async def set_park_position(self) -> None:
        if not self._caps.get("set_park"):
            raise ValueError("This mount cannot set its park position")
        await self._alpaca.put("setpark")

    async def sync(self, coord: SkyCoord) -> None:
        if not self._caps.get("sync"):
            raise ValueError("This mount cannot sync")
        ra_h, dec_deg = self._to_mount(coord)
        await self._alpaca.put("synctocoordinates", RightAscension=ra_h, Declination=dec_deg)

    async def set_tracking(self, enabled: bool, mode: TrackingMode | None = None) -> None:
        a = self._alpaca
        if enabled and mode is not None and mode in _DRIVE_RATES:
            try:
                await a.put("trackingrate", TrackingRate=_DRIVE_RATES[mode])
            except AlpacaError as exc:
                logger.debug("alpaca.mount_tracking_rate_skipped", device=repr(a), mode=mode, error=str(exc))
        await a.put("tracking", Tracking=enabled)

    async def start_move(self, direction: str, rate: str) -> None:
        """Move at *rate* ("<n>x" sidereal or guide/centering/find/max) until stop_move()."""
        a = self._alpaca
        speed = nudge_speed_x_sidereal(rate) * SIDEREAL_DEG_PER_SEC
        max_rate = self._caps.get("max_rate")
        if max_rate:
            speed = min(speed, max_rate)
        if direction in ("E", "W"):
            if not self._caps.get("move_ra"):
                raise ValueError("This mount cannot be moved by hand")
            await a.put("moveaxis", Axis=0, Rate=speed if direction == "W" else -speed)
        elif direction in ("N", "S"):
            if not self._caps.get("move_dec"):
                raise ValueError("This mount cannot be moved by hand")
            flipped = await a.get_or("sideofpier", 0) == 1
            north = speed if not flipped else -speed
            await a.put("moveaxis", Axis=1, Rate=north if direction == "N" else -north)
        else:
            raise ValueError(f"Unknown direction {direction!r}")

    async def stop_move(self) -> None:
        for axis, can in ((0, "move_ra"), (1, "move_dec")):
            if self._caps.get(can):
                try:
                    await self._alpaca.put("moveaxis", Axis=axis, Rate=0)
                except AlpacaError as exc:
                    logger.warning("alpaca.mount_stop_move_failed", device=repr(self._alpaca), axis=axis, error=str(exc))

    async def meridian_flip(self) -> None:
        """Point at the same place from the other side of the pier.

        Mounts that can set SideOfPier are asked to flip; one that stays where it is (or cannot)
        is sent to its own position again, which a mount past the meridian does from the other side.
        """
        a = self._alpaca
        ra_h, dec_deg = float(await a.get("rightascension")), float(await a.get("declination"))
        side = await a.get_or("sideofpier", None)
        if self._caps.get("set_pier_side") and side in (0, 1):
            await a.put("sideofpier", SideOfPier=1 - side)
            await self._wait_until(self._not_slewing, SLEW_TIMEOUT, "meridian flip", interval=0.5)
            if await a.get_or("sideofpier", side) != side:
                return
        await self._slew_to(ra_h, dec_deg)

    async def pulse_guide(self, direction: PulseDirection, duration_ms: int) -> None:
        if not self._caps.get("pulse"):
            raise PulseGuideNotSupported(f"{self.name or 'mount'} cannot pulse guide")
        await alpaca_pulse_guide(self._alpaca, direction, duration_ms)

    async def set_location(self, lat: float, lon: float, alt: float) -> None:
        """Push the site to the mount (best-effort: some mounts keep their own)."""
        a = self._alpaca
        for member, param, value in (("sitelatitude", "SiteLatitude", lat),
                                     ("sitelongitude", "SiteLongitude", lon),
                                     ("siteelevation", "SiteElevation", alt)):
            try:
                await a.put(member, **{param: value})
            except AlpacaError as exc:
                logger.debug("alpaca.mount_site_skipped", device=repr(a), member=member, error=str(exc))
        logger.info("alpaca.mount_location_set", device=repr(a), lat=lat, lon=lon, alt=alt)

    async def set_time_utc(self) -> None:
        """Push the current UTC time (best-effort: many mounts take the computer's clock)."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        try:
            await self._alpaca.put("utcdate", UTCDate=now)
        except AlpacaError as exc:
            logger.debug("alpaca.mount_time_skipped", device=repr(self._alpaca), error=str(exc))
