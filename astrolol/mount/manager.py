import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import structlog

from astrolol.config.user_settings import MountDeviceSettings
from astrolol.core.events import (
    EventBus,
    MountMeridianFlipCompleted,
    MountMeridianFlipStarted,
    MountOperationFailed,
    MountParked,
    MountSlewAborted,
    MountSlewCompleted,
    MountSlewStarted,
    MountSynced,
    MountTargetSet,
    MountTrackingChanged,
    MountUnparked,
)
from astrolol.core.errors import DeviceNotFoundError, DeviceKindError
from astropy.coordinates import SkyCoord

from astrolol.devices.base.models import MountStatus, Target, TrackingMode
from astrolol.devices.manager import DeviceManager
from astrolol.equipment.models import SiteItem
from astrolol.mount.sky import altitude_of
from astrolol.profiles.store import ProfileStore

logger = structlog.get_logger()

SLEW_TIMEOUT = 300.0   # 5 minutes — long slews across the sky
PARK_TIMEOUT = 120.0


@dataclass
class MountController:
    """Per-mount state: tracks any in-progress slew or park task and the current target."""
    device_id: str
    _active_task: asyncio.Task | None = field(default=None, repr=False)
    _target: SkyCoord | None = field(default=None, repr=False)
    _target_name: str | None = field(default=None, repr=False)
    _target_source: str | None = field(default=None, repr=False)
    _target_set_at: datetime | None = field(default=None, repr=False)

    @property
    def is_busy(self) -> bool:
        return self._active_task is not None and not self._active_task.done()


def meridian_flip_due(pier_side: str | None, hour_angle: float | None) -> bool | None:
    """True if the OTA is on the pier side meant for the other half of the sky, so a flip
    would bring it back to the normal side; False if it already is there; None if unknown.

    Pier side follows INDI/ASCOM: "East" = OTA east of the pier, looking west (the normal
    side for western targets, HA >= 0); "West" = looking east (eastern targets, HA < 0).
    A flip from the normal side would put the counterweight up, so it is never "due".
    Northern hemisphere.
    """
    if hour_angle is None or pier_side not in ("East", "West"):
        return None
    ha = (hour_angle + 12.0) % 24.0 - 12.0
    return pier_side != ("East" if ha >= 0 else "West")


_AUTOMATION_INTERVAL = 30  # seconds between automation checks
_HORIZON_REARM_DEG = 1.0   # the horizon action re-arms once the mount is this far above the limit


class MountManager:
    def __init__(
        self,
        device_manager: DeviceManager,
        event_bus: EventBus,
        profile_store: ProfileStore | None = None,
        site_provider: Callable[[], SiteItem | None] | None = None,
    ) -> None:
        self._device_manager = device_manager
        self._event_bus = event_bus
        self._profile_store = profile_store
        # The observing site lives in the active profile's equipment tree; asked for on use.
        self._site_provider = site_provider
        self._controllers: dict[str, MountController] = {}
        # Automation
        self._automation_tasks: dict[str, asyncio.Task] = {}
        self._auto_flip_triggered: set[str] = set()       # device_ids that flipped this transit
        self._auto_park_last: dict[str, tuple[int, int]] = {}  # device_id → (h, m) last parked
        self._horizon_triggered: set[str] = set()          # device_ids that crossed the horizon limit

    # --- Public API ---

    async def set_target(
        self,
        device_id: str,
        coord: SkyCoord,
        name: str | None = None,
        source: str | None = None,
    ) -> Target:
        """Set the current target for the mount. Returns the stored Target."""
        ctrl = self._get_or_create(device_id)
        now = datetime.now(timezone.utc)
        ctrl._target = coord.icrs
        ctrl._target_name = name
        ctrl._target_source = source
        ctrl._target_set_at = now

        icrs = coord.icrs
        await self._event_bus.publish(
            MountTargetSet(
                device_id=device_id,
                ra=icrs.ra.deg,
                dec=icrs.dec.deg,
                name=name,
                source=source,
            )
        )
        logger.info("mount.target_set", device_id=device_id, ra=icrs.ra.deg, dec=icrs.dec.deg, name=name)
        return Target(ra=icrs.ra.deg, dec=icrs.dec.deg, name=name, source=source, set_at=now)

    def get_target(self, device_id: str) -> Target | None:
        """Return the current target, or None if not set."""
        ctrl = self._controllers.get(device_id)
        if ctrl is None or ctrl._target is None:
            return None
        return Target(
            ra=ctrl._target.ra.deg,
            dec=ctrl._target.dec.deg,
            name=ctrl._target_name,
            source=ctrl._target_source,
            set_at=ctrl._target_set_at,  # type: ignore[arg-type]
        )

    async def clear_target(self, device_id: str) -> None:
        """Clear the current target."""
        ctrl = self._get_or_create(device_id)
        ctrl._target = None
        ctrl._target_name = None
        ctrl._target_source = None
        ctrl._target_set_at = None
        logger.info("mount.target_cleared", device_id=device_id)

    async def slew(self, device_id: str) -> None:
        """
        Start a slew to the current target. Returns immediately.
        Subscribe to /ws/events for MountSlewCompleted / MountSlewAborted.
        Raises ValueError if no target is set or the mount is already busy.
        """
        ctrl = self._get_or_create(device_id)
        self._require_idle(ctrl)

        if ctrl._target is None:
            raise ValueError(
                f"Mount '{device_id}' has no target. Call set_target() first."
            )

        coord = ctrl._target
        self._check_above_horizon(device_id, coord)
        icrs = coord.icrs
        ctrl._active_task = asyncio.create_task(
            self._slew_worker(ctrl, coord),
            name=f"mount_slew_{device_id}",
        )
        await self._event_bus.publish(
            MountSlewStarted(device_id=device_id, ra=icrs.ra.deg, dec=icrs.dec.deg)
        )
        logger.info("mount.slew_started", device_id=device_id, ra=icrs.ra.deg, dec=icrs.dec.deg)

    async def stop(self, device_id: str) -> None:
        """
        Abort any in-progress slew or park and halt the motors.
        Safe to call when idle — acts as an emergency stop.
        """
        ctrl = self._get_or_create(device_id)
        mount = self._device_manager.get_mount(device_id)

        if ctrl._active_task and not ctrl._active_task.done():
            ctrl._active_task.cancel()
            try:
                await ctrl._active_task
            except asyncio.CancelledError:
                pass
            ctrl._active_task = None

        # Always send stop to hardware regardless of task state
        try:
            await asyncio.wait_for(mount.stop(), timeout=10.0)
        except Exception as exc:
            logger.warning("mount.stop_error", device_id=device_id, error=str(exc))

        await self._event_bus.publish(MountSlewAborted(device_id=device_id))
        logger.info("mount.stopped", device_id=device_id)

    async def park(self, device_id: str) -> None:
        """Start parking the mount. Returns immediately; events announce completion."""
        ctrl = self._get_or_create(device_id)
        self._require_idle(ctrl)

        ctrl._active_task = asyncio.create_task(
            self._park_worker(ctrl),
            name=f"mount_park_{device_id}",
        )
        logger.info("mount.parking", device_id=device_id)

    async def unpark(self, device_id: str) -> None:
        mount = self._device_manager.get_mount(device_id)
        await mount.unpark()
        await self._event_bus.publish(MountUnparked(device_id=device_id))
        logger.info("mount.unparked", device_id=device_id)

    async def sync(self, device_id: str, coord: SkyCoord) -> None:
        """Sync the mount's coordinate model to the given ICRS position."""
        mount = self._device_manager.get_mount(device_id)
        await mount.sync(coord)
        icrs = coord.icrs
        await self._event_bus.publish(
            MountSynced(device_id=device_id, ra=icrs.ra.deg, dec=icrs.dec.deg)
        )
        logger.info("mount.synced", device_id=device_id, ra=icrs.ra.deg, dec=icrs.dec.deg)

    async def set_tracking(self, device_id: str, enabled: bool, mode: TrackingMode | None = None) -> None:
        mount = self._device_manager.get_mount(device_id)
        await mount.set_tracking(enabled, mode)
        await self._event_bus.publish(
            MountTrackingChanged(device_id=device_id, tracking=enabled, mode=mode)
        )
        logger.info("mount.tracking_changed", device_id=device_id, tracking=enabled, mode=mode)

    async def set_park_position(self, device_id: str) -> None:
        """Set the current position as the park position."""
        mount = self._device_manager.get_mount(device_id)
        await mount.set_park_position()
        logger.info("mount.park_position_set", device_id=device_id)

    async def start_move(self, device_id: str, direction: str, rate: str) -> None:
        """Start continuous directional motion at the given slew rate."""
        mount = self._device_manager.get_mount(device_id)
        await mount.start_move(direction, rate)
        logger.info("mount.move_started", device_id=device_id, direction=direction, rate=rate)

    async def stop_move(self, device_id: str) -> None:
        """Stop all directional motion."""
        mount = self._device_manager.get_mount(device_id)
        await mount.stop_move()
        logger.info("mount.move_stopped", device_id=device_id)

    async def pulse_guide(self, device_id: str, direction: str, duration_ms: int) -> None:
        """Guide pulse; returns once the pulse has completed.

        Optional adapter capability (duck-typed, like set_location). Raises ValueError
        when the mount cannot guide or is busy with a slew/park/flip.
        """
        mount = self._device_manager.get_mount(device_id)
        if not hasattr(mount, "pulse_guide"):
            raise ValueError(f"Mount '{device_id}' does not support pulse guiding.")
        self._require_idle(self._get_or_create(device_id))
        await mount.pulse_guide(direction, duration_ms)
        logger.debug("mount.pulse_guided", device_id=device_id, direction=direction, duration_ms=duration_ms)

    async def meridian_flip(self, device_id: str) -> None:
        """
        Perform a meridian flip: slew to the current position on the opposite pier side.
        Returns immediately; subscribe to events for completion / failure.
        """
        ctrl = self._get_or_create(device_id)
        self._require_idle(ctrl)
        status = await self.get_status(device_id)
        if meridian_flip_due(status.pier_side, status.hour_angle) is False:
            raise ValueError(
                f"No meridian flip needed: pier side {status.pier_side} is already the normal one "
                f"for hour angle {status.hour_angle:+.2f} h"
            )

        ctrl._active_task = asyncio.create_task(
            self._flip_worker(ctrl),
            name=f"mount_flip_{device_id}",
        )
        await self._event_bus.publish(MountMeridianFlipStarted(device_id=device_id))
        logger.info("mount.meridian_flip_started", device_id=device_id)

    async def push_site_data(
        self,
        device_id: str,
        location: SiteItem | None = None,
    ) -> None:
        """Push UTC time (always) and geographic location (when available) to the mount.

        Uses duck-typing so non-INDI adapters that don't implement these methods
        are silently skipped.  Failures are logged as warnings and never propagated
        — this is best-effort initialisation, not a hard requirement for connect.
        """
        mount = self._device_manager.get_mount(device_id)

        if hasattr(mount, "set_time_utc"):
            try:
                await mount.set_time_utc()
            except Exception as exc:
                logger.warning("mount.time_set_failed", device_id=device_id, error=str(exc))

        if location is not None and hasattr(mount, "set_location"):
            try:
                await mount.set_location(location.latitude, location.longitude, location.altitude)
            except Exception as exc:
                logger.warning("mount.location_set_failed", device_id=device_id, error=str(exc))

    async def get_status(self, device_id: str) -> MountStatus:
        mount = self._device_manager.get_mount(device_id)
        return await mount.get_status()

    # --- Limits ---

    async def apply_limits(self, device_id: str) -> None:
        """Push the configured meridian limit to adapters that enforce one (duck-typed, best effort).

        The horizon limit is enforced here instead (GOTO check + automation loop), since it
        only needs the pointing every adapter reports.
        """
        try:
            mount = self._device_manager.get_mount(device_id)
            if hasattr(mount, "set_meridian_limit"):
                await mount.set_meridian_limit(self._get_mount_settings(device_id).meridian_limit_deg)
        except Exception as exc:
            logger.warning("mount.limits_apply_failed", device_id=device_id, error=str(exc))

    def _site(self) -> SiteItem | None:
        if self._site_provider is None:
            return None
        try:
            return self._site_provider()
        except Exception as exc:
            logger.warning("mount.site_lookup_failed", error=str(exc))
            return None

    def _check_above_horizon(self, device_id: str, coord: SkyCoord) -> None:
        """ValueError if the target is below the flat horizon limit (no site known: no check)."""
        site = self._site()
        if site is None:
            return
        limit = self._get_mount_settings(device_id).horizon_min_alt_deg
        alt = altitude_of(coord, datetime.now(timezone.utc), site.latitude, site.longitude)
        if alt < limit:
            raise ValueError(f"Target is below the horizon limit: altitude {alt:.1f}° < {limit:g}°")

    async def _check_horizon(self, device_id: str, cfg: MountDeviceSettings, status: MountStatus) -> None:
        """Apply the horizon action once when a tracking mount sinks below the limit."""
        alt = status.alt
        if alt is None:
            return
        if alt >= cfg.horizon_min_alt_deg + _HORIZON_REARM_DEG:
            self._horizon_triggered.discard(device_id)
            return
        if (
            alt >= cfg.horizon_min_alt_deg
            or cfg.horizon_action == "none"
            or not status.is_tracking
            or status.is_parked
            or device_id in self._horizon_triggered
            or self._get_or_create(device_id).is_busy
        ):
            return
        self._horizon_triggered.add(device_id)
        logger.warning(
            "mount.horizon_limit_reached", device_id=device_id, alt=round(alt, 2),
            limit=cfg.horizon_min_alt_deg, action=cfg.horizon_action,
        )
        if cfg.horizon_action == "park":
            await self.park(device_id)
        else:
            await self.set_tracking(device_id, False)

    # --- Automation ---

    def _get_mount_settings(self, device_id: str) -> MountDeviceSettings:
        if self._profile_store is None:
            return MountDeviceSettings()
        raw = self._profile_store.get_user_settings().mount_settings.get(device_id, {})
        return MountDeviceSettings(**raw)

    def start_automation(self, device_id: str) -> None:
        """Start the automation loop for *device_id* — idempotent, safe to call repeatedly."""
        task = self._automation_tasks.get(device_id)
        if task is not None and not task.done():
            return
        self._automation_tasks[device_id] = asyncio.create_task(
            self._automation_loop(device_id),
            name=f"mount_automation_{device_id}",
        )
        logger.info("mount.automation_started", device_id=device_id)

    async def _automation_loop(self, device_id: str) -> None:
        await self.apply_limits(device_id)
        while True:
            await asyncio.sleep(_AUTOMATION_INTERVAL)
            try:
                await self._check_automation(device_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("mount.automation_error", device_id=device_id, error=str(exc))

    async def _check_automation(self, device_id: str) -> None:
        cfg = self._get_mount_settings(device_id)
        now = datetime.now()

        # ── Auto-park at configured local time ────────────────────────────────
        if cfg.auto_park_enabled and cfg.auto_park_time:
            try:
                th, tm = (int(x) for x in cfg.auto_park_time.split(":"))
            except ValueError:
                logger.warning("mount.automation_bad_park_time", device_id=device_id, value=cfg.auto_park_time)
            else:
                if now.hour == th and now.minute == tm:
                    last = self._auto_park_last.get(device_id)
                    if last != (th, tm):
                        self._auto_park_last[device_id] = (th, tm)
                        ctrl = self._get_or_create(device_id)
                        if not ctrl.is_busy:
                            logger.info("mount.auto_park_triggered", device_id=device_id, time=cfg.auto_park_time)
                            await self.park(device_id)

        try:
            status = await self.get_status(device_id)
        except Exception:
            return

        # ── Horizon limit while tracking ─────────────────────────────────────
        await self._check_horizon(device_id, cfg, status)

        # ── Auto meridian flip when HA exceeds threshold ──────────────────────
        if cfg.auto_flip_enabled:
            ha = status.hour_angle
            if ha is None:
                return
            # Reset flip guard once the mount is clearly east of the meridian
            if ha < -0.5:
                self._auto_flip_triggered.discard(device_id)
            # Trigger flip when HA crosses the threshold
            if (
                ha >= cfg.auto_flip_ha_hours
                and device_id not in self._auto_flip_triggered
                and meridian_flip_due(status.pier_side, ha) is not False
            ):
                self._auto_flip_triggered.add(device_id)
                ctrl = self._get_or_create(device_id)
                if not ctrl.is_busy:
                    logger.info(
                        "mount.auto_flip_triggered",
                        device_id=device_id,
                        ha=round(ha, 3),
                        threshold=cfg.auto_flip_ha_hours,
                    )
                    await self.meridian_flip(device_id)

    # --- Internal ---

    def _get_or_create(self, device_id: str) -> MountController:
        if device_id not in self._controllers:
            self._controllers[device_id] = MountController(device_id=device_id)
        return self._controllers[device_id]

    def _require_idle(self, ctrl: MountController) -> None:
        if ctrl.is_busy:
            raise ValueError(
                f"Mount '{ctrl.device_id}' is busy. Call stop() first."
            )

    async def _slew_worker(self, ctrl: MountController, coord: SkyCoord) -> None:
        device_id = ctrl.device_id
        mount = self._device_manager.get_mount(device_id)
        icrs = coord.icrs
        try:
            await asyncio.wait_for(mount.slew(coord), timeout=SLEW_TIMEOUT)
            await self._event_bus.publish(
                MountSlewCompleted(device_id=device_id, ra=icrs.ra.deg, dec=icrs.dec.deg)
            )
            logger.info("mount.slew_completed", device_id=device_id)
        except asyncio.CancelledError:
            logger.info("mount.slew_cancelled", device_id=device_id)
            raise
        except asyncio.TimeoutError:
            await self._event_bus.publish(MountSlewAborted(device_id=device_id))
            await self._event_bus.publish(
                MountOperationFailed(device_id=device_id, operation="slew", reason="Slew timed out")
            )
            logger.error("mount.slew_timeout", device_id=device_id)
        except Exception as exc:
            await self._event_bus.publish(MountSlewAborted(device_id=device_id))
            await self._event_bus.publish(
                MountOperationFailed(device_id=device_id, operation="slew", reason=str(exc))
            )
            logger.error("mount.slew_error", device_id=device_id, error=str(exc), exc_info=True)
        finally:
            ctrl._active_task = None

    async def _flip_worker(self, ctrl: MountController) -> None:
        device_id = ctrl.device_id
        mount = self._device_manager.get_mount(device_id)
        try:
            await asyncio.wait_for(mount.meridian_flip(), timeout=SLEW_TIMEOUT)
            await self._event_bus.publish(MountMeridianFlipCompleted(device_id=device_id))
            logger.info("mount.meridian_flip_completed", device_id=device_id)
        except asyncio.CancelledError:
            logger.info("mount.meridian_flip_cancelled", device_id=device_id)
            raise
        except asyncio.TimeoutError:
            await self._event_bus.publish(MountSlewAborted(device_id=device_id))
            await self._event_bus.publish(
                MountOperationFailed(device_id=device_id, operation="meridian_flip", reason="Flip timed out")
            )
            logger.error("mount.meridian_flip_timeout", device_id=device_id)
        except Exception as exc:
            await self._event_bus.publish(MountSlewAborted(device_id=device_id))
            await self._event_bus.publish(
                MountOperationFailed(device_id=device_id, operation="meridian_flip", reason=str(exc))
            )
            logger.error("mount.meridian_flip_error", device_id=device_id, error=str(exc), exc_info=True)
        finally:
            ctrl._active_task = None

    async def _park_worker(self, ctrl: MountController) -> None:
        device_id = ctrl.device_id
        mount = self._device_manager.get_mount(device_id)
        try:
            await asyncio.wait_for(mount.park(), timeout=PARK_TIMEOUT)
            await self._event_bus.publish(MountParked(device_id=device_id))
            logger.info("mount.parked", device_id=device_id)
        except asyncio.CancelledError:
            logger.info("mount.park_cancelled", device_id=device_id)
            raise
        except asyncio.TimeoutError:
            await self._event_bus.publish(
                MountOperationFailed(device_id=device_id, operation="park", reason="Park timed out")
            )
            logger.error("mount.park_timeout", device_id=device_id)
        except Exception as exc:
            await self._event_bus.publish(
                MountOperationFailed(device_id=device_id, operation="park", reason=str(exc))
            )
            logger.error("mount.park_error", device_id=device_id, error=str(exc), exc_info=True)
        finally:
            ctrl._active_task = None
