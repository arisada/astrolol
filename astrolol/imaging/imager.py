import asyncio
import shutil
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

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
from astrolol.imaging.models import DitherConfig, ExposureRequest, ExposureResult, ImagerState, ImagerStatus
from astrolol.imaging.preview import fits_to_jpeg, fits_to_jpeg_linear

if TYPE_CHECKING:
    from astrolol.profiles.models import Profile
    from astrolol.profiles.store import ProfileStore

logger = structlog.get_logger()


def _expand_template(
    template: str,
    frame_type: str,
    counter: int,
    duration: float,
    gain: int,
) -> str:
    """Expand % tokens in a save-path template."""
    now = datetime.now(timezone.utc)
    result = template
    result = result.replace("%D", now.strftime("%Y-%m-%d"))
    result = result.replace("%T", now.strftime("%H%M%S"))
    result = result.replace("%U", str(Path.home()))
    result = result.replace("%O", "unknown")
    result = result.replace("%F", frame_type)
    result = result.replace("%C", f"{counter:06d}")
    result = result.replace("%E", f"{duration:.1f}")
    result = result.replace("%G", str(gain))
    return result


@dataclass
class CameraImager:
    """Per-camera state holder. Logic lives in ImagerManager."""
    device_id: str
    state: ImagerState = ImagerState.IDLE
    _loop_task: asyncio.Task | None = field(default=None, repr=False)


_IMAGETYP = {
    "light": "Light Frame",
    "dark":  "Dark Frame",
    "flat":  "Flat Frame",
    "bias":  "Bias Frame",
}


def _write_imagetyp(fits_path: Path, frame_type: str) -> None:
    """Write the standard IMAGETYP FITS keyword unconditionally."""
    imagetyp = _IMAGETYP.get(frame_type, "Light Frame")
    try:
        from astropy.io import fits as astrofits
        with astrofits.open(str(fits_path), mode="update") as hdul:
            hdul[0].header["IMAGETYP"] = (imagetyp, "Frame type")
            hdul.flush()
    except Exception:
        logger.warning("imager.fits_imagetyp_failed", fits=str(fits_path))


def _patch_fits_headers(fits_path: Path, profile: "Profile", ra: float | None, dec: float | None) -> None:
    """Inject observatory and telescope metadata into an existing FITS file."""
    try:
        from astropy.io import fits as astrofits
        with astrofits.open(str(fits_path), mode="update") as hdul:
            hdr = hdul[0].header
            if profile.telescope:
                hdr["TELESCOP"] = (profile.telescope.name, "Telescope name")
                hdr["FOCALLEN"] = (profile.telescope.focal_length, "[mm] Focal length")
                hdr["APTDIA"] = (profile.telescope.aperture, "[mm] Aperture diameter")
                hdr["APTAREA"] = (
                    3.14159265 * (profile.telescope.aperture / 2) ** 2,
                    "[mm^2] Aperture area",
                )
            if profile.location:
                hdr["SITELAT"] = (profile.location.latitude, "[deg] Observer latitude")
                hdr["SITELONG"] = (profile.location.longitude, "[deg] Observer longitude")
                hdr["SITEELEV"] = (profile.location.altitude, "[m] Observer altitude")
                if profile.location.name:
                    hdr["SITENAME"] = (profile.location.name, "Observer location name")
            if ra is not None:
                hdr["RA"] = (ra * 15.0, "[deg] Right ascension (J2000)")
            if dec is not None:
                hdr["DEC"] = (dec, "[deg] Declination (J2000)")
            hdul.flush()
    except Exception:
        logger.warning("imager.fits_header_patch_failed", fits=str(fits_path))


class ImagerManager:
    def __init__(
        self,
        device_manager: DeviceManager,
        event_bus: EventBus,
        images_dir: Path | None = None,
        profile_store: "ProfileStore | None" = None,
    ) -> None:
        self._device_manager = device_manager
        self._event_bus = event_bus
        self._images_dir = images_dir or settings.images_dir
        self._imagers: dict[str, CameraImager] = {}
        self._active_profile: "Profile | None" = None
        self._profile_store = profile_store
        self._save_counters: dict[str, int] = {}
        # Optional dither hook set by the PHD2 plugin on startup.
        # Signature: async (config: DitherConfig) -> None
        self._dither_fn: Callable[[DitherConfig], Awaitable[None]] | None = None

    def set_context(self, profile: "Profile | None") -> None:
        """Called when a profile is activated or cleared."""
        self._active_profile = profile

    async def push_scope_info(self, device_id: str) -> None:
        """Push telescope optics from the active profile to the camera's SCOPE_INFO."""
        profile = self._active_profile
        if profile is None or profile.telescope is None:
            return
        try:
            camera = self._device_manager.get_camera(device_id)
            push = getattr(camera, "push_scope_info", None)
            if push is not None:
                await push(profile.telescope.focal_length, profile.telescope.aperture)
        except Exception as exc:
            logger.warning("imager.scope_info_push_failed", device_id=device_id, error=str(exc))

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
        if imager._loop_task is None or imager._loop_task.done():
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
        params = ExposureParams(
            duration=request.duration,
            gain=request.gain,
            binning=request.binning,
            frame_type=request.frame_type,
        )

        # Snapshot mount RA/DEC before the shutter opens (best represents pointing)
        ra: float | None = None
        dec: float | None = None
        profile = self._active_profile
        if profile is not None:
            mount_role = next(
                (pd for pd in profile.devices if pd.role == "mount"), None
            )
            if mount_role is not None:
                try:
                    mount = self._device_manager.get_mount(mount_role.config.device_id)
                    status = await mount.status()
                    ra = status.ra
                    dec = status.dec
                except Exception:
                    pass  # mount not connected or query failed — skip RA/DEC

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
        self._images_dir.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(_write_imagetyp, fits_path, request.frame_type)
        if profile is not None:
            await asyncio.to_thread(_patch_fits_headers, fits_path, profile, ra, dec)

        # Optionally move to save directory using the configured template
        if request.save and self._profile_store is not None:
            user_cfg = self._profile_store.get_user_settings()
            counter = self._save_counters.get(device_id, 0) + 1
            self._save_counters[device_id] = counter
            dir_part = _expand_template(
                user_cfg.save_dir_template, request.frame_type, counter, request.duration, request.gain
            )
            file_part = _expand_template(
                user_cfg.save_filename_template, request.frame_type, counter, request.duration, request.gain
            )
            save_dir = Path(dir_part).expanduser()
            save_dir.mkdir(parents=True, exist_ok=True)
            final_fits = save_dir / f"{file_part}.fits"
            try:
                await asyncio.to_thread(shutil.move, str(fits_path), str(final_fits))
                fits_path = final_fits
            except Exception:
                logger.warning("imager.save_move_failed", src=str(fits_path), dst=str(final_fits))

        # Generate two previews (auto-stretch + linear) — both live in images_dir
        preview_path = self._preview_path(fits_path.stem, self._images_dir, suffix="auto")
        preview_path_linear = self._preview_path(fits_path.stem, self._images_dir, suffix="linear")
        await asyncio.to_thread(fits_to_jpeg, fits_path, preview_path, settings.jpeg_quality)
        await asyncio.to_thread(fits_to_jpeg_linear, fits_path, preview_path_linear, settings.jpeg_quality)

        result = ExposureResult(
            device_id=device_id,
            fits_path=str(fits_path),
            preview_path=str(preview_path),
            preview_path_linear=str(preview_path_linear),
            duration=image.exposure_duration,
            width=image.width,
            height=image.height,
        )
        await self._event_bus.publish(
            ExposureCompleted(
                device_id=device_id,
                fits_path=result.fits_path,
                preview_path=result.preview_path,
                preview_path_linear=result.preview_path_linear,
                duration=result.duration,
                width=result.width,
                height=result.height,
            )
        )
        imager.state = ImagerState.IDLE
        log.info("imager.exposure_completed", fits=result.fits_path)
        return result

    async def _loop_worker(self, imager: CameraImager, request: ExposureRequest) -> None:
        count = 0
        last_dither_at = _time.monotonic()
        try:
            while request.count is None or count < request.count:
                # Between-frame dither (skip before the very first exposure)
                if count > 0 and request.dither is not None and self._dither_fn is not None:
                    cfg = request.dither
                    should_dither = False
                    if cfg.every_frames is not None and count % cfg.every_frames == 0:
                        should_dither = True
                    if cfg.every_minutes is not None:
                        elapsed_min = (_time.monotonic() - last_dither_at) / 60.0
                        if elapsed_min >= cfg.every_minutes:
                            should_dither = True
                    if should_dither:
                        try:
                            logger.info("imager.dithering", device_id=imager.device_id, frame=count)
                            await self._dither_fn(cfg)
                            last_dither_at = _time.monotonic()
                        except Exception as exc:
                            logger.warning(
                                "imager.dither_failed",
                                device_id=imager.device_id,
                                error=str(exc),
                            )

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
    def _preview_path(stem: str, directory: Path, suffix: str = "auto") -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        return directory / f"{stem}_{ts}_preview_{suffix}.jpg"
