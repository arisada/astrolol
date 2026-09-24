"""Real Sky-Watcher mount adapter (adapter_key "eqmod").

Talks the motor controller protocol (protocol.py) over serial (transport.py) and does
all sky geometry itself (geometry.py). Sync is a software offset: the controller's
counters are never rewritten, so raw counts always mean "steps from power-on home".
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import structlog
from astropy.coordinates import SkyCoord

from astrolol.devices.base.models import DeviceState, MountStatus, TrackingMode
from plugins.eqmod.geometry import (
    MountGeometry,
    PierSide,
    SyncOffset,
    alt_az,
    icrs_to_jnow,
    jnow_to_icrs,
    local_sidereal_time_h,
    opposite,
    pier_side_of,
)
from plugins.eqmod.protocol import (
    HIGH_SPEED_THRESHOLD_DEG_PER_SEC,
    SIDEREAL_DEG_PER_SEC,
    Axis,
    SkywatcherProtocol,
    step_period_for_rate,
)
from plugins.eqmod.transport import SerialTransport, detect_baudrate

logger = structlog.get_logger()

TRACKING_RATES_DEG_PER_SEC = {
    TrackingMode.SIDEREAL: SIDEREAL_DEG_PER_SEC,
    TrackingMode.LUNAR: 14.685 / 3600.0,
    TrackingMode.SOLAR: 15.0 / 3600.0,
}
# Multiples of sidereal; "max" exceeds 128x so it uses the controller's high-speed mode.
NUDGE_RATES_X_SIDEREAL = {"guide": 0.5, "centering": 16.0, "find": 64.0, "max": 400.0}
AXIS_STOP_TIMEOUT = 10.0          # seconds
AXIS_STOP_POLL_INTERVAL = 0.1     # seconds
GOTO_TIMEOUT = 240.0              # seconds, per pass
GOTO_POLL_INTERVAL = 0.25         # seconds
GOTO_PASSES = 2                   # second pass corrects for sky motion during the first
GOTO_MIN_COUNTS = 10              # smaller corrections are skipped
COORDS_PUSH_INTERVAL = 2.0        # seconds
STATE_PERSIST_INTERVAL = 60.0     # seconds, while idle
STATE_TOLERANCE_DEG = 0.5         # counts must match the last saved state this closely to trust it


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_path(key: str) -> Path:
    env = os.environ.get("ASTROLOL_DATA_DIR")
    return (Path(env) if env else Path.home() / ".astrolol") / "eqmod" / f"{key}.json"


class EqmodNotReadyError(RuntimeError):
    """Operation needs something not available yet (e.g. a site location)."""


@dataclass
class AxisInfo:
    cpr: int
    high_speed_ratio: int


class EqmodMount:
    DEFAULT_CONNECT_PARAMS = {"port": "/dev/ttyUSB0"}

    def __init__(
        self,
        port: str | None = None,
        baudrate: int | None = None,
        ra_reverse: bool = False,
        dec_reverse: bool = False,
        state_key: str | None = None,
        transport_factory: Callable[[str, int], Any] = SerialTransport,
        **_kwargs: object,
    ) -> None:
        self._port = port
        self._requested_baudrate = baudrate
        self._reverse = {Axis.RA: bool(ra_reverse), Axis.DEC: bool(dec_reverse)}
        self._state_key = state_key or (Path(port).name if port else "eqmod")
        self._transport_factory = transport_factory
        self._transport: Any = None
        self._proto: SkywatcherProtocol | None = None
        self._baudrate: int | None = None
        self._board_version: int | None = None
        self._timer_freq: int = 0
        self._axes: dict[Axis, AxisInfo] = {}
        self._geometry: MountGeometry | None = None
        self._connected = False
        self._tracking = False
        self._tracking_mode = TrackingMode.SIDEREAL
        self._nudging: set[Axis] = set()
        self._slewing = False
        self._is_parked = False
        self._park_counts: tuple[int, int] = (0, 0)
        self._location: tuple[float, float, float] | None = None  # (lat, lon, alt_m)
        self._on_coords_cb: Callable[..., None] | None = None
        self._coords_task: asyncio.Task | None = None
        self._last_persist = 0.0

    # --- Lifecycle ---

    async def connect(self) -> None:
        if not self._port:
            raise ValueError('eqmod needs a "port" connect param, e.g. {"port": "/dev/ttyUSB0"}')
        baudrate = self._requested_baudrate or await detect_baudrate(self._port)
        transport = self._transport_factory(self._port, baudrate)
        await transport.open()
        proto = SkywatcherProtocol(transport)
        try:
            self._board_version = await proto.inquire_motor_board_version()
            self._timer_freq = await proto.inquire_timer_freq()
            for axis in (Axis.RA, Axis.DEC):
                self._axes[axis] = AxisInfo(
                    cpr=await proto.inquire_cpr(axis),
                    high_speed_ratio=await proto.inquire_high_speed_ratio(axis),
                )
            await proto.initialize(Axis.BOTH)
            # Motors keep running across an astrolol restart; pick up tracking if it's on.
            ra = await proto.inquire_status(Axis.RA)
            self._tracking = ra.running and ra.tracking_mode and not ra.fast
            counts = (await proto.inquire_position(Axis.RA), await proto.inquire_position(Axis.DEC))
        except Exception:
            await transport.close()
            raise
        self._transport, self._proto, self._baudrate = transport, proto, baudrate
        self._geometry = MountGeometry(
            self._axes[Axis.RA].cpr, self._axes[Axis.DEC].cpr,
            self._reverse[Axis.RA], self._reverse[Axis.DEC],
        )
        self._restore_state(*counts)
        self._connected = True
        self._persist(*counts)
        self._coords_task = asyncio.create_task(self._coords_pump())
        logger.info(
            "eqmod.connected", port=self._port, baudrate=baudrate,
            board_version=hex(self._board_version), timer_freq=self._timer_freq,
            ra_cpr=self._axes[Axis.RA].cpr, dec_cpr=self._axes[Axis.DEC].cpr,
            tracking=self._tracking, parked=self._is_parked, synced=self._geometry.offset is not None,
        )

    async def disconnect(self) -> None:
        if self._coords_task is not None:
            self._coords_task.cancel()
            try:
                await self._coords_task
            except asyncio.CancelledError:
                pass
            self._coords_task = None
        # Stop hand-held nudges, but leave tracking running like a real handset would.
        try:
            for axis in list(self._nudging):
                await self._stop_axis(axis)
            if self._proto is not None:
                self._persist(*await self._read_counts())
        except Exception as exc:
            logger.warning("eqmod.disconnect_cleanup_failed", error=str(exc))
        self._nudging.clear()
        self._connected = False
        if self._transport is not None:
            await self._transport.close()
        self._transport = self._proto = None

    async def ping(self) -> bool:
        if self._proto is None:
            return False
        try:
            await self._proto.inquire_status(Axis.RA)
            return True
        except Exception:
            return False

    async def get_status(self) -> MountStatus:
        if not self._connected:
            return MountStatus(state=DeviceState.DISCONNECTED)
        try:
            c = self._compute_coords(*await self._read_counts())
        except Exception as exc:
            logger.warning("eqmod.status_read_failed", error=str(exc))
            return MountStatus(state=DeviceState.ERROR, is_tracking=self._tracking, is_parked=self._is_parked)
        return MountStatus(
            state=DeviceState.CONNECTED,
            is_tracking=self._tracking,
            is_parked=self._is_parked,
            is_slewing=self._slewing or bool(self._nudging),
            is_synced=self._geometry is not None and self._geometry.offset is not None,
            **c,
        )

    # --- Site data (duck-typed by MountManager.push_site_data) ---

    async def set_location(self, lat: float, lon: float, alt: float) -> None:
        self._location = (lat, lon, alt)
        logger.info("eqmod.location_set", lat=lat, lon=lon, alt=alt)

    async def set_time_utc(self) -> None:
        pass  # the controller has no clock; all time maths uses the host clock

    # --- Motion ---

    async def slew(self, coord: SkyCoord) -> None:
        await self._goto_sky(coord)

    async def meridian_flip(self) -> None:
        geo = self._require_geometry()
        lst = self._lst()
        ra_jnow, dec, _, side = geo.pointing(*await self._read_counts(), lst)
        await self._goto_sky(jnow_to_icrs(ra_jnow, dec, _now()), side=opposite(side))

    async def sync(self, coord: SkyCoord) -> None:
        geo = self._require_geometry()
        lst = self._lst()
        ra_jnow, dec = icrs_to_jnow(coord, _now())
        counts = await self._read_counts()
        offset = geo.sync(*counts, ra_jnow, dec, lst)
        self._is_parked = False
        self._persist(*counts)
        logger.info("eqmod.synced", ra_axis_h=offset.ra_axis_h, dec_axis_deg=offset.dec_axis_deg)
        await self._push_coords()

    async def park(self) -> None:
        await self._stop_all_motion()
        try:
            self._slewing = True
            await self._goto_counts(*self._park_counts)
        except asyncio.CancelledError as cancelled:
            await self._halt_all_quietly()
            raise cancelled
        finally:
            self._slewing = False
        self._is_parked = True
        self._persist(*await self._read_counts())
        await self._push_coords()

    async def unpark(self) -> None:
        self._is_parked = False
        self._persist(*await self._read_counts())
        await self._push_coords()

    async def set_park_position(self) -> None:
        self._park_counts = await self._read_counts()
        self._persist(*self._park_counts)
        logger.info("eqmod.park_position_set", ra_counts=self._park_counts[0], dec_counts=self._park_counts[1])

    async def start_move(self, direction: str, rate: str) -> None:
        if direction in ("W", "E"):
            axis, positive = Axis.RA, direction == "W"  # westward = tracking direction
        elif direction in ("N", "S"):
            # Which way the Dec axis must turn for "north" depends on the pier side.
            ra_c, dec_c = await self._read_counts()
            side = pier_side_of(self._require_geometry().counts_to_axes(ra_c, dec_c).dec_axis_deg)
            axis, positive = Axis.DEC, (direction == "N") == (side is PierSide.WEST)
        else:
            raise ValueError(f"Invalid direction: {direction!r}")
        speed = NUDGE_RATES_X_SIDEREAL.get(rate, NUDGE_RATES_X_SIDEREAL["centering"]) * SIDEREAL_DEG_PER_SEC
        self._is_parked = False
        await self._run_axis(axis, speed, positive)
        self._nudging.add(axis)
        logger.info("eqmod.nudge_started", axis=axis.name, direction=direction, rate=rate)

    async def stop_move(self) -> None:
        nudged = set(self._nudging)
        for axis in nudged:
            await self._stop_axis(axis)
        self._nudging.clear()
        if Axis.RA in nudged and self._tracking:
            await self._start_tracking()
        self._persist(*await self._read_counts())

    async def set_tracking(self, enabled: bool, mode: TrackingMode | None = None) -> None:
        if mode is not None:
            self._tracking_mode = mode
        if enabled:
            await self._start_tracking()
        else:
            await self._stop_axis(Axis.RA)
            self._tracking = False
        self._nudging.discard(Axis.RA)
        self._persist(*await self._read_counts())

    async def stop(self) -> None:
        self._nudging.clear()
        self._tracking = False
        self._slewing = False
        await self._halt_all()
        self._persist(*await self._read_counts())

    # --- Live coordinate push (duck-typed by DeviceManager, same contract as IndiMount) ---

    def set_coords_listener(self, cb: Callable[..., None] | None) -> None:
        self._on_coords_cb = cb
        if cb is not None and self._connected:
            asyncio.get_running_loop().create_task(self._push_coords())

    async def _push_coords(self) -> None:
        if self._on_coords_cb is None or not self._connected:
            return
        c = self._compute_coords(*await self._read_counts())
        try:
            self._on_coords_cb(
                c["ra"], c["dec"], c["ra_jnow"], c["dec_jnow"], c["alt"], c["az"],
                c["pier_side"], c["hour_angle"], c["lst"], self._tracking, self._is_parked,
            )
        except Exception:
            pass

    async def _coords_pump(self) -> None:
        while True:
            await asyncio.sleep(COORDS_PUSH_INTERVAL)
            try:
                await self._push_coords()
                if not self._slewing and time.monotonic() - self._last_persist > STATE_PERSIST_INTERVAL:
                    self._persist(*await self._read_counts())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("eqmod.coords_push_failed", error=str(exc))

    # --- Device-specific (not part of IMount) ---

    async def set_led_brightness(self, value: int) -> None:
        await self._require_proto().set_polar_led_brightness(round(value * 255 / 100))

    async def diagnostics(self) -> dict[str, Any]:
        proto = self._require_proto()
        axes: dict[str, Any] = {}
        for axis, info in self._axes.items():
            position = await proto.inquire_position(axis)
            axes[axis.name] = {
                "cpr": info.cpr,
                "high_speed_ratio": info.high_speed_ratio,
                "position_counts": position,
                "position_degrees": position * 360.0 / info.cpr,
                "step_period": await proto.inquire_step_period(axis),
                "status": asdict(await proto.inquire_status(axis)),
                "extended_status": await proto.inquire_extended_status(axis),
                "reversed": self._reverse[axis],
            }
        offset = self._geometry.offset if self._geometry else None
        return {
            "port": self._port,
            "baudrate": self._baudrate,
            "board_version": f"{self._board_version:06X}" if self._board_version is not None else None,
            "timer_freq": self._timer_freq,
            "tracking": self._tracking,
            "tracking_mode": self._tracking_mode.value,
            "nudging": sorted(a.name for a in self._nudging),
            "location": list(self._location) if self._location else None,
            "parked": self._is_parked,
            "park_counts": list(self._park_counts),
            "sync_offset": asdict(offset) if offset else None,
            "axes": axes,
        }

    # --- Internal: geometry ---

    def _require_proto(self) -> SkywatcherProtocol:
        if self._proto is None:
            raise RuntimeError("eqmod mount is not connected")
        return self._proto

    def _require_geometry(self) -> MountGeometry:
        if self._geometry is None:
            raise RuntimeError("eqmod mount is not connected")
        return self._geometry

    def _lst(self) -> float:
        if self._location is None:
            raise EqmodNotReadyError(
                "No site location: add a Site to the active profile so the mount knows where it is"
            )
        return local_sidereal_time_h(_now(), self._location[1])

    async def _read_counts(self) -> tuple[int, int]:
        proto = self._require_proto()
        return await proto.inquire_position(Axis.RA), await proto.inquire_position(Axis.DEC)

    def _compute_coords(self, ra_counts: int, dec_counts: int) -> dict[str, Any]:
        geo = self._require_geometry()
        side = pier_side_of(geo.counts_to_axes(ra_counts, dec_counts).dec_axis_deg)
        out: dict[str, Any] = {
            "ra": None, "dec": None, "ra_jnow": None, "dec_jnow": None,
            "alt": None, "az": None, "hour_angle": None, "lst": None, "pier_side": side.value,
        }
        if self._location is None:
            return out
        now = _now()
        lst = local_sidereal_time_h(now, self._location[1])
        ra_jnow, dec, ha, _ = geo.pointing(ra_counts, dec_counts, lst)
        icrs = jnow_to_icrs(ra_jnow, dec, now)
        alt, az = alt_az(ha, dec, self._location[0])
        out.update(
            ra=float(icrs.ra.hour), dec=float(icrs.dec.deg), ra_jnow=ra_jnow, dec_jnow=dec,
            alt=alt, az=az, hour_angle=ha, lst=lst,
        )
        return out

    # --- Internal: motion ---

    async def _goto_sky(self, coord: SkyCoord, side: PierSide | None = None) -> None:
        geo = self._require_geometry()
        self._lst()  # fail fast without a location, before anything moves
        await self._stop_all_motion()
        self._is_parked = False
        self._slewing = True
        try:
            for _ in range(GOTO_PASSES):
                now = _now()
                ra_jnow, dec = icrs_to_jnow(coord, now)
                ra_c, dec_c, side = geo.target_counts(ra_jnow, dec, self._lst(), side)
                logger.info("eqmod.goto_pass", ra_counts=ra_c, dec_counts=dec_c, pier_side=side.value)
                if not await self._goto_counts(ra_c, dec_c):
                    break
            await self._start_tracking()
        except asyncio.CancelledError as cancelled:
            await self._halt_all_quietly()
            raise cancelled
        finally:
            self._slewing = False
        self._persist(*await self._read_counts())
        await self._push_coords()

    async def _goto_counts(self, ra_target: int, dec_target: int) -> bool:
        """GOTO both axes to raw counts; returns False if already there."""
        proto = self._require_proto()
        moving = []
        for axis, target in ((Axis.RA, ra_target), (Axis.DEC, dec_target)):
            await self._stop_axis(axis)
            delta = target - await proto.inquire_position(axis)
            if abs(delta) < GOTO_MIN_COUNTS:
                continue
            await proto.set_motion_mode(axis, tracking=False, fast=True, ccw=delta < 0)
            await proto.set_goto_target_increment(axis, abs(delta))
            await proto.start_motion(axis)
            moving.append(axis)
        deadline = time.monotonic() + GOTO_TIMEOUT
        for axis in moving:
            while (await proto.inquire_status(axis)).running:
                if time.monotonic() > deadline:
                    await self._halt_all_quietly()
                    raise TimeoutError(f"GOTO did not finish within {GOTO_TIMEOUT}s")
                await asyncio.sleep(GOTO_POLL_INTERVAL)
        return bool(moving)

    async def _halt_all(self) -> None:
        """Instant-stop each axis separately (channel "3" is not relied on); try both, then raise."""
        proto = self._require_proto()
        errors: list[Exception] = []
        for axis in (Axis.RA, Axis.DEC):
            try:
                await proto.instant_stop(axis)
            except Exception as exc:
                logger.error("eqmod.instant_stop_failed", axis=axis.name, error=str(exc), exc_info=True)
                errors.append(exc)
        if errors:
            raise errors[0]

    async def _halt_all_quietly(self) -> None:
        """Used while aborting: a failed stop must not replace the cancellation/timeout in flight."""
        try:
            await self._halt_all()
        except Exception:
            pass  # already logged per axis

    async def _start_tracking(self) -> None:
        await self._run_axis(Axis.RA, TRACKING_RATES_DEG_PER_SEC[self._tracking_mode], True)
        self._tracking = True

    async def _stop_all_motion(self) -> None:
        for axis in (Axis.RA, Axis.DEC):
            await self._stop_axis(axis)
        self._nudging.clear()
        self._tracking = False

    async def _run_axis(self, axis: Axis, deg_per_sec: float, positive: bool) -> None:
        """Run one axis in Speed mode; positive = axis angle increasing (westward on RA)."""
        proto = self._require_proto()
        info = self._axes[axis]
        fast = deg_per_sec > HIGH_SPEED_THRESHOLD_DEG_PER_SEC
        period = step_period_for_rate(
            deg_per_sec, info.cpr, self._timer_freq, info.high_speed_ratio if fast else 1
        )
        await self._stop_axis(axis)
        # CW increases counts; a reversed axis maps increasing angle to decreasing counts.
        await proto.set_motion_mode(axis, tracking=True, fast=fast, ccw=positive == self._reverse[axis])
        await proto.set_step_period(axis, period)
        await proto.start_motion(axis)

    async def _stop_axis(self, axis: Axis) -> None:
        """Decelerating stop, then wait until the controller reports the axis stopped."""
        proto = self._require_proto()
        await proto.stop_motion(axis)
        deadline = time.monotonic() + AXIS_STOP_TIMEOUT
        while (await proto.inquire_status(axis)).running:
            if time.monotonic() > deadline:
                await proto.instant_stop(axis)
                raise TimeoutError(f"{axis.name} axis did not stop within {AXIS_STOP_TIMEOUT}s")
            await asyncio.sleep(AXIS_STOP_POLL_INTERVAL)

    # --- Internal: persistence ---

    def _restore_state(self, ra_counts: int, dec_counts: int) -> None:
        """Reuse the saved sync offset only if the counts show the mount wasn't power-cycled/moved."""
        geo = self._require_geometry()
        tolerance = STATE_TOLERANCE_DEG / 360.0
        at_home = (abs(ra_counts) <= tolerance * geo.ra_cpr and abs(dec_counts) <= tolerance * geo.dec_cpr)
        try:
            state = json.loads(_state_path(self._state_key).read_text())
        except (OSError, ValueError):
            state = {}
        if park := state.get("park_counts"):
            self._park_counts = (int(park[0]), int(park[1]))
        last = state.get("last")
        if last and self._counts_match(last, ra_counts, dec_counts):
            if offset := state.get("sync_offset"):
                geo.offset = SyncOffset(**offset)
            self._is_parked = bool(state.get("is_parked", at_home))
            return
        if last:
            logger.warning(
                "eqmod.saved_state_discarded", state_key=self._state_key,
                reason="controller counts do not match the last saved position (power cycle or moved)",
            )
        self._is_parked = at_home

    def _counts_match(self, last: dict[str, Any], ra_counts: int, dec_counts: int) -> bool:
        geo = self._require_geometry()
        try:
            elapsed = (_now() - datetime.fromisoformat(last["time"])).total_seconds()
            expected_ra = float(last["ra_counts"])
            if last.get("tracking"):
                ra_sign = -1 if self._reverse[Axis.RA] else 1
                expected_ra += ra_sign * SIDEREAL_DEG_PER_SEC * elapsed * geo.ra_cpr / 360.0
            expected_dec = float(last["dec_counts"])
        except (KeyError, TypeError, ValueError):
            return False
        tolerance = STATE_TOLERANCE_DEG / 360.0
        return (abs(ra_counts - expected_ra) <= tolerance * geo.ra_cpr
                and abs(dec_counts - expected_dec) <= tolerance * geo.dec_cpr)

    def _persist(self, ra_counts: int, dec_counts: int) -> None:
        geo = self._require_geometry()
        data = {
            "sync_offset": asdict(geo.offset) if geo.offset else None,
            "park_counts": list(self._park_counts),
            "is_parked": self._is_parked,
            "last": {
                "ra_counts": ra_counts,
                "dec_counts": dec_counts,
                "time": _now().isoformat(),
                "tracking": self._tracking,
            },
        }
        path = _state_path(self._state_key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
            self._last_persist = time.monotonic()
        except OSError as exc:
            logger.warning("eqmod.state_persist_failed", path=str(path), error=str(exc))
