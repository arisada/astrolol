import asyncio
from dataclasses import dataclass, field

import structlog

from astrolol.core.events import (
    EventBus,
    MountOperationFailed,
    MountParked,
    MountSlewAborted,
    MountSlewCompleted,
    MountSlewStarted,
    MountSynced,
    MountTrackingChanged,
    MountUnparked,
)
from astrolol.core.errors import DeviceNotFoundError, DeviceKindError
from astrolol.devices.base.models import MountStatus, SlewTarget, TrackingMode
from astrolol.devices.manager import DeviceManager

logger = structlog.get_logger()

SLEW_TIMEOUT = 300.0   # 5 minutes — long slews across the sky
PARK_TIMEOUT = 120.0


@dataclass
class MountController:
    """Per-mount state: tracks any in-progress slew or park task."""
    device_id: str
    _active_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def is_busy(self) -> bool:
        return self._active_task is not None and not self._active_task.done()


class MountManager:
    def __init__(self, device_manager: DeviceManager, event_bus: EventBus) -> None:
        self._device_manager = device_manager
        self._event_bus = event_bus
        self._controllers: dict[str, MountController] = {}

    # --- Public API ---

    async def slew(self, device_id: str, target: SlewTarget) -> None:
        """
        Start a slew to the given RA/Dec. Returns immediately.
        Subscribe to /ws/events for MountSlewCompleted / MountSlewAborted.
        Raises ValueError if the mount is already busy.
        """
        ctrl = self._get_or_create(device_id)
        self._require_idle(ctrl)

        ctrl._active_task = asyncio.create_task(
            self._slew_worker(ctrl, target),
            name=f"mount_slew_{device_id}",
        )
        await self._event_bus.publish(
            MountSlewStarted(device_id=device_id, ra=target.ra, dec=target.dec)
        )
        logger.info("mount.slew_started", device_id=device_id, ra=target.ra, dec=target.dec)

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

    async def sync(self, device_id: str, target: SlewTarget) -> None:
        """Sync the mount's coordinate model to the given position."""
        mount = self._device_manager.get_mount(device_id)
        await mount.sync(target)
        await self._event_bus.publish(
            MountSynced(device_id=device_id, ra=target.ra, dec=target.dec)
        )
        logger.info("mount.synced", device_id=device_id, ra=target.ra, dec=target.dec)

    async def set_tracking(self, device_id: str, enabled: bool, mode: TrackingMode | None = None) -> None:
        mount = self._device_manager.get_mount(device_id)
        await mount.set_tracking(enabled, mode)
        await self._event_bus.publish(
            MountTrackingChanged(device_id=device_id, tracking=enabled, mode=mode)
        )
        logger.info("mount.tracking_changed", device_id=device_id, tracking=enabled, mode=mode)

    async def get_status(self, device_id: str) -> MountStatus:
        mount = self._device_manager.get_mount(device_id)
        return await mount.get_status()

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

    async def _slew_worker(self, ctrl: MountController, target: SlewTarget) -> None:
        device_id = ctrl.device_id
        mount = self._device_manager.get_mount(device_id)
        try:
            await asyncio.wait_for(mount.slew(target), timeout=SLEW_TIMEOUT)
            await self._event_bus.publish(
                MountSlewCompleted(device_id=device_id, ra=target.ra, dec=target.dec)
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
            logger.error("mount.slew_error", device_id=device_id, error=str(exc))
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
            logger.error("mount.park_error", device_id=device_id, error=str(exc))
        finally:
            ctrl._active_task = None
