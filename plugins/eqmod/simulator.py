"""Generic, protocol-agnostic mount emulator — Phase 1 of the EQMOD driver.

This class exists to validate astrolol's device-adapter integration contract
(registry wiring, the full IMount call surface MountManager actually uses,
and reconnect-without-resync persistence) *before* any real EQMOD/SynScan
wire-protocol code is written. It knows nothing about EQMOD's serial command
set — that's Phase 2, built behind the same IMount contract this class
already satisfies.

Design points carried over from planning:
- "Facing north" park position is modeled as ICRS Dec=90 (the NCP) — a
  genuinely fixed, always-valid sky *direction* regardless of RA. That does
  NOT mean the reported RA *number* freezes there: a real driver still
  computes RA = LST - fixed_hour_angle even at the pole, so RA keeps
  drifting with time while parked too, same as anywhere else. Only Dec is
  special; RA drift is unconditional whenever untracked.
- Position is stored as a fixed ICRS reference (_ra/_dec) plus the wall-clock
  time it was fixed (_position_time), not as a continuously-updated value.
  An untracked equatorial mount holds a fixed *mechanical* (hour-angle)
  position while the sky rotates under it, so its ICRS RA drifts at the
  sidereal rate until the next slew/sync/nudge/tracking-toggle re-fixes it
  — see _effective_ra(). Dec never drifts (Earth rotates about the polar
  axis). Every write to position must go through _fix_position() so this
  stays correct. The very first park reference (before any real position is
  known) seeds its RA from actual Greenwich sidereal time rather than a
  bare 0.0, so a fresh mount doesn't look suspiciously frozen either.
- Alt/Az/HA/LST require an observer location, which nothing hands the mount
  directly — MountManager.push_site_data() calls set_location()/
  set_time_utc() via duck-typing after connect(), same as it does for
  IndiMount (see devices/indi/mount.py). Until set_location() has been
  called (e.g. no active profile has a Site item), those fields stay None —
  that's correct, not a bug: there's nothing to compute them from.
- Slew and nudge move incrementally over a simulated realistic duration
  (see _SLEW_RATE_DEG_PER_SEC / _NUDGE_RATES_DEG_PER_SEC) rather than
  teleporting, pushing intermediate positions so the UI shows real motion.
- State is persisted per state_key under ~/.astrolol/eqmod/ (or
  $ASTROLOL_DATA_DIR/eqmod/) so a restarted astrolol process reconnects
  without losing the plate-solve sync — mirroring how a real EQMOD mount's
  motor controller keeps running independently of the serial connection.
  _position_time is persisted too, so drift keeps accruing correctly across
  a restart exactly as it would on real hardware (nothing stops the sky
  turning just because astrolol is down).
- A "hw_token" models the mount's own persistent identity, separate from
  astrolol's saved calibration. It only changes via simulate_power_cycle(),
  which is not part of IMount — it exists purely so tests can prove that a
  *real* power loss (not just an astrolol restart) correctly invalidates a
  stale sync instead of silently trusting it.
- set_coords_listener()/_push_coords() mirror devices/indi/mount.py's
  contract so DeviceManager's duck-typed wiring pushes live MountCoordsUpdated
  events over the WebSocket exactly as it does for a real INDI mount. Unlike
  INDI (where the driver itself emits property-change events we react to),
  nothing else here generates those pushes, so a periodic pump task
  (_coords_pump) fires one every COORDS_PUSH_INTERVAL while connected — this
  is also what makes sidereal drift visible live in the UI while idle.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import astropy.units as u
import structlog
from astropy.coordinates import TETE, AltAz, EarthLocation, SkyCoord
from astropy.time import Time

from astrolol.devices.base.models import DeviceState, MountStatus, TrackingMode

logger = structlog.get_logger()

_SIDEREAL_DEG_PER_SEC = 360.0 / 86164.0905  # sidereal day, in seconds
COORDS_PUSH_INTERVAL = 2.0  # seconds between live coordinate pushes while connected

_SLEW_RATE_DEG_PER_SEC = 3.0  # plausible GOTO speed for a mid-size GEM
_SLEW_STEP_INTERVAL = 0.2     # seconds between intermediate slew position pushes
_SLEW_MIN_DURATION = 0.5      # floor so even a tiny slew still "moves"

_NUDGE_RATES_DEG_PER_SEC = {
    "guide": 0.01,
    "centering": 0.5,
    "find": 2.0,
    "max": 4.0,
}
_NUDGE_STEP_INTERVAL = 0.2  # seconds between intermediate nudge position pushes
_GUIDE_RATE_X_SIDEREAL = 0.5


def _now() -> datetime:
    """Wall-clock time, as its own function so tests can monkeypatch it."""
    return datetime.now(timezone.utc)


# --- Persisted state (module-level so simulate_power_cycle() needs no live instance) ---

def _state_dir() -> Path:
    env = os.environ.get("ASTROLOL_DATA_DIR")
    base = Path(env) if env else Path.home() / ".astrolol"
    return base / "eqmod"


def _state_path(state_key: str) -> Path:
    return _state_dir() / f"{state_key}.json"


def _seed_park_ra_deg() -> float:
    """Ground the very first default park RA in real sidereal time instead of
    an arbitrary constant, so a fresh mount's reported RA already looks
    time-of-day-plausible before any site location is known. Uses Greenwich
    (longitude 0) since no observer location exists yet at this point —
    set_location() + ongoing drift correct for the real site once it's
    pushed."""
    return float(Time.now().sidereal_time("apparent", "greenwich").hour) * 15.0


def _default_state() -> dict[str, Any]:
    return {
        "hw_token": secrets.token_hex(8),
        "position": None,          # {"hw_token_at_write", "ra_icrs_deg", "dec_icrs_deg", "is_synced", "position_time"}
        "tracking_enabled": False,
        "tracking_mode": TrackingMode.SIDEREAL.value,
        "is_parked": True,
        "park_ra_icrs_deg": _seed_park_ra_deg(),
        "park_dec_icrs_deg": 90.0,  # NCP — see module docstring
    }


def _load_state(state_key: str) -> dict[str, Any]:
    path = _state_path(state_key)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if data.get("hw_token"):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    data = _default_state()
    _write_state(state_key, data)
    return data


def _write_state(state_key: str, data: dict[str, Any]) -> None:
    path = _state_path(state_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def simulate_power_cycle(state_key: str = "default") -> None:
    """Test-only: simulate the physical mount losing power while astrolol
    wasn't watching it. Not part of IMount — real hardware doesn't need this,
    it really does lose its step reference on power loss. The next connect()
    for *state_key* will discard any previously-established sync rather than
    trust it.
    """
    data = _load_state(state_key)
    data["hw_token"] = secrets.token_hex(8)
    _write_state(state_key, data)


def _wrapped_ra_delta(start_ra: float, target_ra: float) -> float:
    """Shortest signed RA delta (degrees) from start to target, handling the
    0/360 wrap (e.g. 350 -> 10 is +20, not -340)."""
    return ((target_ra - start_ra + 180.0) % 360.0) - 180.0


class EqmodSimMount:
    """IMount adapter with simulated physics. Registered as adapter_key
    'eqmod_sim'. See module docstring for the design rationale.
    """

    DEFAULT_CONNECT_PARAMS = {"state_key": "default"}

    def __init__(self, state_key: str = "default", **_kwargs: object) -> None:
        self._state_key = state_key
        self._connected = False
        self._hw_token: str = ""
        self._ra: float | None = None     # ICRS degrees — reference as of _position_time
        self._dec: float | None = None    # ICRS degrees — never drifts
        self._position_time: datetime = _now()
        self._is_synced = False
        self._tracking_enabled = False
        self._tracking_mode = TrackingMode.SIDEREAL
        self._is_parked = True
        self._park_ra = 0.0
        self._park_dec = 90.0
        self._pier_side = "West"
        self._location: tuple[float, float, float] | None = None  # (lat, lon, alt_m) degrees/metres
        self._moving_direction: str | None = None
        self._on_coords_cb: Callable[..., None] | None = None
        self._coords_task: asyncio.Task | None = None
        self._slew_task: asyncio.Task | None = None
        self._nudge_task: asyncio.Task | None = None
        # Not part of IMount — a placeholder proving the plugin-owned
        # settings/API escape hatch for device-specific knobs (see
        # plugins/eqmod/settings.py). Real EQMOD-specific knobs get added
        # here one at a time as the actual driver needs them.
        self._led_brightness = 50

    # --- IMount ---

    async def connect(self) -> None:
        state = _load_state(self._state_key)
        self._hw_token = state["hw_token"]
        self._tracking_mode = TrackingMode(state["tracking_mode"])
        self._is_parked = state["is_parked"]
        self._park_ra = state["park_ra_icrs_deg"]
        self._park_dec = state["park_dec_icrs_deg"]

        pos = state["position"]
        if pos is not None and pos["hw_token_at_write"] == self._hw_token:
            # Same hardware session as the last write — astrolol may have
            # restarted, but the (simulated) mount never lost power. Restore
            # the original position_time (not "now") so sidereal drift
            # continues to accrue across the restart exactly as it would on
            # real hardware.
            self._ra = pos["ra_icrs_deg"]
            self._dec = pos["dec_icrs_deg"]
            self._is_synced = pos["is_synced"]
            self._position_time = (
                datetime.fromisoformat(pos["position_time"])
                if pos.get("position_time") else _now()
            )
            self._tracking_enabled = state["tracking_enabled"]
        else:
            if pos is not None:
                logger.warning(
                    "eqmod_sim.stale_position_discarded",
                    state_key=self._state_key,
                    reason="simulated hardware power cycle detected",
                )
            if self._is_parked:
                # The park reference is mechanically known regardless of
                # whether the mount lost power — nothing moved it.
                self._ra, self._dec, self._is_synced = self._park_ra, self._park_dec, True
            else:
                self._ra, self._dec, self._is_synced = None, None, False
            self._position_time = _now()
            self._tracking_enabled = False  # motors can't have kept running through a power loss

        self._connected = True
        self._persist()
        self._coords_task = asyncio.create_task(self._coords_pump())

    async def disconnect(self) -> None:
        self._connected = False
        await self._cancel_task("_coords_task")
        await self._cancel_task("_slew_task")
        await self._cancel_task("_nudge_task")

    async def slew(self, coord: SkyCoord) -> None:
        await self._cancel_task("_nudge_task")
        icrs = coord.icrs
        target_ra, target_dec = icrs.ra.deg, icrs.dec.deg
        start_ra = self._effective_ra()
        start_dec = self._dec
        if start_ra is None or start_dec is None:
            start_ra, start_dec = target_ra, target_dec

        sep = SkyCoord(ra=start_ra * u.deg, dec=start_dec * u.deg, frame="icrs").separation(
            SkyCoord(ra=target_ra * u.deg, dec=target_dec * u.deg, frame="icrs")
        ).deg
        duration = max(sep / _SLEW_RATE_DEG_PER_SEC, _SLEW_MIN_DURATION)
        steps = max(int(duration / _SLEW_STEP_INTERVAL), 1)
        ra_delta = _wrapped_ra_delta(start_ra, target_ra)
        dec_delta = target_dec - start_dec

        async def _run() -> None:
            try:
                for i in range(1, steps + 1):
                    await asyncio.sleep(duration / steps)
                    frac = i / steps
                    self._fix_position(
                        (start_ra + ra_delta * frac) % 360.0,
                        start_dec + dec_delta * frac,
                    )
                    self._push_coords()
                # Only snap exactly to target on normal completion (avoids
                # accumulated float error from the interpolation steps).
                self._fix_position(target_ra, target_dec)
            except asyncio.CancelledError:
                # Stopped mid-slew — stay wherever the last step left it,
                # same as a real mount's emergency stop. Do NOT jump to
                # target here.
                raise
            finally:
                self._is_parked = False
                self._persist()
                self._push_coords()

        self._slew_task = asyncio.create_task(_run())
        try:
            await self._slew_task
        finally:
            self._slew_task = None

    async def stop(self) -> None:
        self._moving_direction = None
        await self._cancel_task("_slew_task")
        await self._cancel_task("_nudge_task")

    async def park(self) -> None:
        await self.slew(SkyCoord(ra=self._park_ra * u.deg, dec=self._park_dec * u.deg, frame="icrs"))
        self._is_parked = True
        self._is_synced = True
        self._tracking_enabled = False
        self._persist()
        self._push_coords()

    async def unpark(self) -> None:
        self._is_parked = False
        self._persist()
        self._push_coords()

    async def sync(self, coord: SkyCoord) -> None:
        icrs = coord.icrs
        self._fix_position(icrs.ra.deg, icrs.dec.deg)
        self._is_synced = True
        self._persist()
        self._push_coords()

    async def set_tracking(self, enabled: bool, mode: TrackingMode | None = None) -> None:
        # Collapse any pending drift into a fixed reference before flipping
        # the flag, so _position_time/_ra stay meaningful either way.
        self._fix_position(self._effective_ra(), self._dec)
        self._tracking_enabled = enabled
        if mode is not None:
            self._tracking_mode = mode
        self._persist()
        self._push_coords()

    async def set_park_position(self) -> None:
        """Save the current position as the park reference (mirrors INDI's
        PARK_CURRENT) — this is the "parking mode" knob from the original
        design: point the mount where you want it parked, then call this
        once."""
        ra = self._effective_ra()
        if ra is None or self._dec is None:
            raise RuntimeError("Cannot set park position: current position is unknown (unsynced).")
        self._park_ra, self._park_dec = ra, self._dec
        self._persist()

    async def start_move(self, direction: str, rate: str) -> None:
        if direction not in ("N", "S", "E", "W"):
            raise ValueError(f"Invalid direction: {direction!r}")
        await self._cancel_task("_slew_task")
        await self._cancel_task("_nudge_task")
        self._moving_direction = direction
        self._is_parked = False
        speed = _NUDGE_RATES_DEG_PER_SEC.get(rate, _NUDGE_RATES_DEG_PER_SEC["centering"])

        async def _run() -> None:
            try:
                while True:
                    await asyncio.sleep(_NUDGE_STEP_INTERVAL)
                    step = speed * _NUDGE_STEP_INTERVAL
                    ra = self._effective_ra() or 0.0
                    dec = self._dec or 0.0
                    if direction == "N":
                        dec = min(90.0, dec + step)
                    elif direction == "S":
                        dec = max(-90.0, dec - step)
                    elif direction == "E":
                        ra = (ra + step) % 360.0
                    elif direction == "W":
                        ra = (ra - step) % 360.0
                    self._fix_position(ra, dec)
                    self._push_coords()
            except asyncio.CancelledError:
                pass
            finally:
                self._persist()

        self._nudge_task = asyncio.create_task(_run())

    async def stop_move(self) -> None:
        self._moving_direction = None
        await self._cancel_task("_nudge_task")

    async def pulse_guide(self, direction: str, duration_ms: int) -> None:
        """Moves the pointing by guide rate x duration (0.5x sidereal), like a real guide pulse."""
        if direction not in ("N", "S", "E", "W"):
            raise ValueError(f"Invalid direction: {direction!r}")
        if self._is_parked:
            raise ValueError("Cannot guide: the mount is parked")
        if self._slew_task is not None or self._nudge_task is not None:
            raise ValueError("Cannot guide: the mount is moving")
        await asyncio.sleep(duration_ms / 1000.0)
        step = _GUIDE_RATE_X_SIDEREAL * _SIDEREAL_DEG_PER_SEC * duration_ms / 1000.0
        ra = self._effective_ra() or 0.0
        dec = self._dec or 0.0
        if direction == "N":
            dec = min(90.0, dec + step)
        elif direction == "S":
            dec = max(-90.0, dec - step)
        elif direction == "E":
            ra = (ra + step) % 360.0
        else:
            ra = (ra - step) % 360.0
        self._fix_position(ra, dec)
        self._push_coords()

    async def meridian_flip(self) -> None:
        await asyncio.sleep(0.05)
        self._pier_side = "East" if self._pier_side == "West" else "West"
        self._push_coords()

    async def get_status(self) -> MountStatus:
        state = DeviceState.CONNECTED if self._connected else DeviceState.DISCONNECTED
        c = self._compute_coords()
        return MountStatus(
            state=state,
            ra=c["ra"],
            dec=c["dec"],
            ra_jnow=c["ra_jnow"],
            dec_jnow=c["dec_jnow"],
            alt=c["alt"],
            az=c["az"],
            is_tracking=self._tracking_enabled,
            is_parked=self._is_parked,
            is_synced=self._is_synced,
            pier_side=self._pier_side,
            hour_angle=c["hour_angle"],
            lst=c["lst"],
        )

    async def ping(self) -> bool:
        return self._connected

    # --- Location/time (optional — duck-typed by MountManager.push_site_data) ---

    async def set_location(self, lat: float, lon: float, alt: float) -> None:
        """Needed to compute Alt/Az/HA/LST — the simulated hardware has no
        concept of location at all (a real EQMOD motor board doesn't either;
        this math lives entirely in driver software, same as here)."""
        self._location = (lat, lon, alt)
        self._push_coords()

    async def set_time_utc(self) -> None:
        """No-op: every computation here already uses the OS wall clock via
        _now(), so there's no separate device clock to seed. Implemented
        anyway so MountManager.push_site_data()'s hasattr check finds it,
        matching IndiMount's contract instead of silently no-opping."""
        pass

    # --- Live coordinate push (duck-typed by DeviceManager, mirrors IndiMount) ---

    def set_coords_listener(self, cb: Callable[..., None] | None) -> None:
        """Signature: cb(ra, dec, ra_jnow, dec_jnow, alt, az, pier_side,
        hour_angle, lst, is_tracking, is_parked) — see
        devices/indi/mount.py's set_coords_listener for the full contract.
        Fires immediately on registration, like the INDI adapter does, so
        the UI has correct initial state without waiting for the pump.
        """
        self._on_coords_cb = cb
        if cb is not None:
            self._push_coords()

    def _push_coords(self) -> None:
        if self._on_coords_cb is None:
            return
        c = self._compute_coords()
        try:
            self._on_coords_cb(
                c["ra"], c["dec"], c["ra_jnow"], c["dec_jnow"], c["alt"], c["az"],
                self._pier_side, c["hour_angle"], c["lst"],
                self._tracking_enabled, self._is_parked,
            )
        except Exception:
            pass

    async def _coords_pump(self) -> None:
        """Periodically re-push coordinates while connected — the only thing
        that makes idle sidereal drift visible in the live UI without the
        user triggering another operation. Real INDI mounts do the
        equivalent by periodically reporting EQUATORIAL_EOD_COORD."""
        try:
            while True:
                await asyncio.sleep(COORDS_PUSH_INTERVAL)
                self._push_coords()
        except asyncio.CancelledError:
            pass

    # --- Device-specific, not part of IMount (see __init__ comment) ---

    def get_led_brightness(self) -> int:
        return self._led_brightness

    async def set_led_brightness(self, value: int) -> None:
        self._led_brightness = value

    # --- Internal ---

    async def _cancel_task(self, attr: str) -> None:
        task: asyncio.Task | None = getattr(self, attr)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        setattr(self, attr, None)

    def _fix_position(self, ra: float | None, dec: float | None) -> None:
        """Set the reference position and reset the drift clock. Every write
        to position must go through here — see _effective_ra()."""
        self._ra = ra
        self._dec = dec
        self._position_time = _now()

    def _effective_ra(self) -> float | None:
        """Current RA (ICRS degrees), accounting for sidereal drift while
        untracked. Applies regardless of Dec — see module docstring: the
        pole makes the *direction* independent of RA, not the reported
        number, which a real driver still derives from LST."""
        if self._ra is None:
            return None
        if self._tracking_enabled:
            return self._ra
        elapsed = (_now() - self._position_time).total_seconds()
        return (self._ra + _SIDEREAL_DEG_PER_SEC * elapsed) % 360.0

    def _compute_coords(self) -> dict[str, float | None]:
        """Full coordinate set: ICRS ra/dec (hours/degrees), JNow ra/dec, and
        (when a location has been pushed) alt/az/hour_angle/lst."""
        out: dict[str, float | None] = {
            "ra": None, "dec": None, "ra_jnow": None, "dec_jnow": None,
            "alt": None, "az": None, "hour_angle": None, "lst": None,
        }
        ra_deg = self._effective_ra()
        dec = self._dec
        if ra_deg is None or dec is None:
            return out

        now = Time.now()
        icrs = SkyCoord(ra=ra_deg * u.deg, dec=dec * u.deg, frame="icrs")
        jnow = icrs.transform_to(TETE(obstime=now))
        out["ra"] = icrs.ra.hour
        out["dec"] = icrs.dec.deg
        out["ra_jnow"] = jnow.ra.hour
        out["dec_jnow"] = jnow.dec.deg

        if self._location is not None:
            lat, lon, alt_m = self._location
            location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=alt_m * u.m)
            lst = now.sidereal_time("apparent", longitude=lon * u.deg)
            out["lst"] = lst.hour
            ha = lst.hour - jnow.ra.hour
            while ha > 12:
                ha -= 24
            while ha < -12:
                ha += 24
            out["hour_angle"] = ha
            altaz = icrs.transform_to(AltAz(obstime=now, location=location))
            out["alt"] = altaz.alt.deg
            out["az"] = altaz.az.deg

        return out

    def _persist(self) -> None:
        data = {
            "hw_token": self._hw_token,
            "position": (
                {
                    "hw_token_at_write": self._hw_token,
                    "ra_icrs_deg": self._ra,
                    "dec_icrs_deg": self._dec,
                    "is_synced": self._is_synced,
                    "position_time": self._position_time.isoformat(),
                }
                if self._ra is not None and self._dec is not None
                else None
            ),
            "tracking_enabled": self._tracking_enabled,
            "tracking_mode": self._tracking_mode.value,
            "is_parked": self._is_parked,
            "park_ra_icrs_deg": self._park_ra,
            "park_dec_icrs_deg": self._park_dec,
        }
        _write_state(self._state_key, data)
