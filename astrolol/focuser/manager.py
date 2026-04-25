import asyncio
from dataclasses import dataclass, field

import structlog

from astrolol.core.events import EventBus, FocuserHalted, FocuserMoveCompleted, FocuserMoveStarted
from astrolol.devices.base.models import FocuserStatus
from astrolol.devices.manager import DeviceManager

logger = structlog.get_logger()

MOVE_TIMEOUT = 120.0  # 2 minutes — generous for large focuser travels


@dataclass
class FocuserController:
    """Per-focuser state: tracks any in-progress move task."""
    device_id: str
    _active_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def is_busy(self) -> bool:
        return self._active_task is not None and not self._active_task.done()


class FocuserManager:
    def __init__(self, device_manager: DeviceManager, event_bus: EventBus) -> None:
        self._device_manager = device_manager
        self._event_bus = event_bus
        self._controllers: dict[str, FocuserController] = {}

    # --- Public API ---

    async def move_to(self, device_id: str, position: int) -> None:
        """Move to an absolute position. Returns immediately; events announce completion."""
        ctrl = self._get_or_create(device_id)
        self._require_idle(ctrl)
        ctrl._active_task = asyncio.create_task(
            self._move_worker(ctrl, position),
            name=f"focuser_move_{device_id}",
        )
        await self._event_bus.publish(
            FocuserMoveStarted(device_id=device_id, target_position=position)
        )
        logger.info("focuser.move_started", device_id=device_id, target=position)

    async def move_by(self, device_id: str, steps: int) -> None:
        """Move by a relative number of steps (positive = out, negative = in)."""
        ctrl = self._get_or_create(device_id)
        self._require_idle(ctrl)

        focuser = self._device_manager.get_focuser(device_id)
        status = await focuser.get_status()
        current = status.position or 0
        target = max(0, current + steps)

        ctrl._active_task = asyncio.create_task(
            self._move_worker(ctrl, target),
            name=f"focuser_move_{device_id}",
        )
        await self._event_bus.publish(
            FocuserMoveStarted(device_id=device_id, target_position=target)
        )
        logger.info("focuser.move_started", device_id=device_id, target=target, steps=steps)

    async def halt(self, device_id: str) -> None:
        """Stop any in-progress move and halt the motor."""
        ctrl = self._get_or_create(device_id)
        focuser = self._device_manager.get_focuser(device_id)

        if ctrl._active_task and not ctrl._active_task.done():
            ctrl._active_task.cancel()
            try:
                await ctrl._active_task
            except asyncio.CancelledError:
                pass
            ctrl._active_task = None

        try:
            await asyncio.wait_for(focuser.halt(), timeout=10.0)
        except Exception as exc:
            logger.warning("focuser.halt_error", device_id=device_id, error=str(exc))

        status = await focuser.get_status()
        await self._event_bus.publish(
            FocuserHalted(device_id=device_id, position=status.position)
        )
        logger.info("focuser.halted", device_id=device_id, position=status.position)

    async def get_status(self, device_id: str) -> FocuserStatus:
        focuser = self._device_manager.get_focuser(device_id)
        return await focuser.get_status()

    # --- Internal ---

    def _get_or_create(self, device_id: str) -> FocuserController:
        if device_id not in self._controllers:
            self._controllers[device_id] = FocuserController(device_id=device_id)
        return self._controllers[device_id]

    def _require_idle(self, ctrl: FocuserController) -> None:
        if ctrl.is_busy:
            raise ValueError(
                f"Focuser '{ctrl.device_id}' is already moving. Call halt() first."
            )

    async def _move_worker(self, ctrl: FocuserController, target: int) -> None:
        device_id = ctrl.device_id
        focuser = self._device_manager.get_focuser(device_id)
        try:
            await asyncio.wait_for(focuser.move_to(target), timeout=MOVE_TIMEOUT)
            status = await focuser.get_status()
            position = status.position if status.position is not None else target
            await self._event_bus.publish(
                FocuserMoveCompleted(device_id=device_id, position=position)
            )
            logger.info("focuser.move_completed", device_id=device_id, position=position)
        except asyncio.CancelledError:
            logger.info("focuser.move_cancelled", device_id=device_id)
            raise
        except asyncio.TimeoutError:
            logger.error("focuser.move_timeout", device_id=device_id)
        except Exception as exc:
            logger.error("focuser.move_error", device_id=device_id, error=str(exc), exc_info=True)
        finally:
            ctrl._active_task = None
