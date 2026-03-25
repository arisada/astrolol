import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

from astrolol.config.settings import settings
from astrolol.core.errors import DeviceNotFoundError
from astrolol.core.events import (
    EventBus,
    ExposureCompleted,
    ExposureFailed,
    ExposureStarted,
    LoopStarted,
    LoopStopped,
)
from astrolol.devices.base.models import ExposureParams
from astrolol.devices.manager import DeviceManager
from astrolol.imaging.models import ExposureRequest, ExposureResult, ImagerState, ImagerStatus
from astrolol.imaging.preview import fits_to_jpeg

logger = structlog.get_logger()


@dataclass
class CameraImager:
    """Per-camera state holder. Logic lives in ImagerManager."""
    device_id: str
    state: ImagerState = ImagerState.IDLE
    _loop_task: asyncio.Task | None = field(default=None, repr=False)


class ImagerManager:
    def __init__(
        self,
        device_manager: DeviceManager,
        event_bus: EventBus,
        images_dir: Path | None = None,
    ) -> None:
        self._device_manager = device_manager
        self._event_bus = event_bus
        self._images_dir = images_dir or settings.images_dir
        self._imagers: dict[str, CameraImager] = {}

    # --- Public API ---

    async def expose(self, device_id: str, request: ExposureRequest) -> ExposureResult:
        """Take a single exposure. Raises if camera is already busy."""
        imager = self._get_or_create(device_id)
        self._require_idle(imager)
        return await self._do_expose(imager, request)

    async def start_loop(self, device_id: str, request: ExposureRequest) -> None:
        """Start a looping exposure sequence. Returns immediately; events stream results."""
        imager = self._get_or_create(device_id)
        self._require_idle(imager)
        imager.state = ImagerState.LOOPING
        imager._loop_task = asyncio.create_task(
            self._loop_worker(imager, request),
            name=f"imager_loop_{device_id}",
        )
        await self._event_bus.publish(LoopStarted(device_id=device_id))
        logger.info("imager.loop_started", device_id=device_id)

    async def stop_loop(self, device_id: str) -> None:
        """Stop a running loop after the current exposure finishes."""
        imager = self._get_or_create(device_id)
        if imager.state != ImagerState.LOOPING or imager._loop_task is None:
            raise ValueError(f"Camera '{device_id}' is not looping.")
        imager._loop_task.cancel()
        try:
            await imager._loop_task
        except asyncio.CancelledError:
            pass
        imager._loop_task = None
        imager.state = ImagerState.IDLE
        await self._event_bus.publish(LoopStopped(device_id=device_id))
        logger.info("imager.loop_stopped", device_id=device_id)

    def get_status(self, device_id: str) -> ImagerStatus:
        imager = self._get_or_create(device_id)
        return ImagerStatus(device_id=device_id, state=imager.state)

    def all_statuses(self) -> list[ImagerStatus]:
        return [ImagerStatus(device_id=d, state=i.state) for d, i in self._imagers.items()]

    # --- Internal ---

    def _get_or_create(self, device_id: str) -> CameraImager:
        if device_id not in self._imagers:
            self._imagers[device_id] = CameraImager(device_id=device_id)
        return self._imagers[device_id]

    def _require_idle(self, imager: CameraImager) -> None:
        if imager.state != ImagerState.IDLE:
            raise ValueError(
                f"Camera '{imager.device_id}' is busy ({imager.state.value}). "
                "Stop the current operation first."
            )

    async def _do_expose(
        self, imager: CameraImager, request: ExposureRequest
    ) -> ExposureResult:
        device_id = imager.device_id
        log = logger.bind(device_id=device_id, duration=request.duration)

        camera = self._device_manager.get_camera(device_id)
        params = ExposureParams(duration=request.duration, gain=request.gain, binning=request.binning)

        imager.state = ImagerState.EXPOSING
        await self._event_bus.publish(
            ExposureStarted(
                device_id=device_id,
                duration=request.duration,
                gain=request.gain,
                binning=request.binning,
            )
        )
        log.info("imager.exposing")

        try:
            image = await camera.expose(params)
        except Exception as exc:
            imager.state = ImagerState.IDLE
            reason = str(exc)
            await self._event_bus.publish(ExposureFailed(device_id=device_id, reason=reason))
            log.error("imager.exposure_failed", error=reason)
            raise

        fits_path = Path(image.fits_path)
        preview_path = self._preview_path(fits_path)
        self._images_dir.mkdir(parents=True, exist_ok=True)
        fits_to_jpeg(fits_path, preview_path, quality=settings.jpeg_quality)

        result = ExposureResult(
            device_id=device_id,
            fits_path=str(fits_path),
            preview_path=str(preview_path),
            duration=image.exposure_duration,
            width=image.width,
            height=image.height,
        )
        await self._event_bus.publish(
            ExposureCompleted(
                device_id=device_id,
                fits_path=result.fits_path,
                preview_path=result.preview_path,
                duration=result.duration,
                width=result.width,
                height=result.height,
            )
        )
        log.info("imager.exposure_completed", fits=result.fits_path)
        return result

    async def _loop_worker(self, imager: CameraImager, request: ExposureRequest) -> None:
        count = 0
        try:
            while request.count is None or count < request.count:
                await self._do_expose(imager, request)
                imager.state = ImagerState.LOOPING  # restore after _do_expose sets EXPOSING
                count += 1
                # Yield to the event loop so cancel() is processed between exposures
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info("imager.loop_cancelled", device_id=imager.device_id, exposures=count)
            raise
        except Exception as exc:
            imager.state = ImagerState.ERROR
            logger.error("imager.loop_error", device_id=imager.device_id, error=str(exc))
        finally:
            if imager.state not in (ImagerState.ERROR,):
                imager.state = ImagerState.IDLE

    @staticmethod
    def _preview_path(fits_path: Path) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        return fits_path.parent / f"{fits_path.stem}_{ts}_preview.jpg"
