"""
INDI camera adapter — implements ICamera using IndiClient.

INDI CCD properties used:
  CCD_EXPOSURE   NUMBER  CCD_EXPOSURE_VALUE  — trigger + duration
  CCD1           BLOB    CCD1                — image data
  CCD_TEMPERATURE NUMBER CCD_TEMPERATURE_VALUE
  CCD_COOLER     SWITCH  COOLER_ON / COOLER_OFF
  CCD_INFO        NUMBER CCD_MAX_X, CCD_MAX_Y
  CCD_BINNING    NUMBER  HOR_BIN, VER_BIN
  CCD_GAIN       NUMBER  GAIN  (not all cameras have this)
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import structlog

from astrolol.config.settings import settings
from astrolol.devices.base.models import (
    CameraStatus,
    DeviceState,
    ExposureParams,
    Image,
)
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()


class IndiCamera:
    """ICamera implementation backed by an INDI CCD driver."""

    # adapter key used when registering with the DeviceRegistry
    ADAPTER_KEY = "indi_camera"

    def __init__(
        self,
        device_name: str,
        client: IndiClient,
        images_dir: Path | None = None,
        *,
        pre_connect_props: dict | None = None,
        exposure_timeout_extra: float = 60.0,
    ) -> None:
        self._device_name = device_name
        self._client = client
        self._pre_connect_props = pre_connect_props
        self._images_dir = images_dir or settings.images_dir
        self._exposure_timeout_extra = exposure_timeout_extra
        self._state = DeviceState.DISCONNECTED
        self._image_counter = 0
        self._current_upload_dir: Path | None = None  # set while UPLOAD_LOCAL is active

    # ------------------------------------------------------------------
    # ICamera protocol
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

    # CCD_FRAME_TYPE switch element names used by INDI drivers
    _FRAME_TYPE_ELEMENTS = {
        "light": "FRAME_LIGHT",
        "dark":  "FRAME_DARK",
        "flat":  "FRAME_FLAT",
        "bias":  "FRAME_BIAS",
    }

    async def expose(self, params: ExposureParams) -> Image:
        self._state = DeviceState.BUSY

        # Set frame type if supported (best-effort)
        indi_frame = self._FRAME_TYPE_ELEMENTS.get(params.frame_type, "FRAME_LIGHT")
        try:
            await self._client.set_switch(
                self._device_name, "CCD_FRAME_TYPE", [indi_frame]
            )
        except Exception as exc:
            logger.debug(
                "indi.camera_frame_type_skipped",
                device=self._device_name,
                frame_type=params.frame_type,
                error=str(exc),
            )

        # Set binning if supported (best-effort)
        try:
            await self._client.set_number(
                self._device_name,
                "CCD_BINNING",
                {"HOR_BIN": float(params.binning), "VER_BIN": float(params.binning)},
            )
        except Exception as exc:
            logger.debug(
                "indi.camera_binning_skipped",
                device=self._device_name,
                error=str(exc),
            )

        # Set gain if supported (best-effort)
        if params.gain is not None:
            try:
                await self._client.set_number(
                    self._device_name,
                    "CCD_GAIN",
                    {"GAIN": float(params.gain)},
                )
            except Exception as exc:
                logger.debug(
                    "indi.camera_gain_skipped",
                    device=self._device_name,
                    error=str(exc),
                )

        timeout = params.duration + self._exposure_timeout_extra

        if self._current_upload_dir is not None:
            # LOCAL upload mode: indiserver writes the FITS to disk and sends a
            # device Message "... Image saved to /path" instead of forwarding the
            # setBLOBVector.  Clear any stale path before triggering so we can't
            # accidentally pick up a result from a previous exposure.
            self._client.clear_local_image_path(self._device_name)
            await self._client.set_number(
                self._device_name,
                "CCD_EXPOSURE",
                {"CCD_EXPOSURE_VALUE": params.duration},
            )
            fits_path = await self._client.wait_for_local_image(self._device_name, timeout=timeout)
        else:
            # CLIENT mode: enable BLOBs for this camera only for the duration of
            # this exposure.  "Never" is the default; keeping BLOBs off between
            # exposures prevents unmanaged devices (e.g. a PHD2 guide camera) from
            # ever sending frames to us and blocking delivery of our own images.
            await self._client.enable_blob(self._device_name)
            await self._client.set_number(
                self._device_name,
                "CCD_EXPOSURE",
                {"CCD_EXPOSURE_VALUE": params.duration},
            )
            blob = await self._client.wait_for_blob(self._device_name, "CCD1", timeout=timeout)
            # Save blob data received over the network to disk
            self._images_dir.mkdir(parents=True, exist_ok=True)
            self._image_counter += 1
            fits_path = self._images_dir / f"frame_{self._image_counter:06d}.fits"
            def _save() -> None:
                with open(fits_path, "wb") as f:
                    f.write(blob.data)
            await asyncio.to_thread(_save)

        # Read dimensions from CCD_INFO (best-effort)
        width, height = await self._read_dimensions()

        self._state = DeviceState.CONNECTED
        logger.info(
            "indi.camera_exposure_done",
            device=self._device_name,
            fits=str(fits_path),
            duration=params.duration,
        )
        return Image(
            fits_path=str(fits_path),
            width=width,
            height=height,
            exposure_duration=params.duration,
        )

    async def abort(self) -> None:
        try:
            await self._client.set_switch(
                self._device_name, "CCD_ABORT_EXPOSURE", ["ABORT"]
            )
        except Exception as exc:
            logger.warning("indi.camera_abort_failed", device=self._device_name, error=str(exc))
        finally:
            self._state = DeviceState.CONNECTED

    async def get_status(self) -> CameraStatus:
        temperature: float | None = None
        cooler_on = False
        cooler_power: float | None = None

        # Read temperature — try getfloatvalue first, fall back to direct member access
        # (some simulator builds put CCD_TEMPERATURE in Alert state which can cause
        # getfloatvalue to misbehave in certain indipyclient builds)
        temp_v = self._client._get_vector(self._device_name, "CCD_TEMPERATURE")
        if temp_v is not None:
            try:
                temperature = temp_v.getfloatvalue("CCD_TEMPERATURE_VALUE")
            except Exception:
                try:
                    member = temp_v.data.get("CCD_TEMPERATURE_VALUE")
                    if member is not None:
                        temperature = float(str(member.membervalue).strip())
                except Exception:
                    pass

        cooler_on_val = self._client.get_switch_state_nowait(
            self._device_name, "CCD_COOLER", "COOLER_ON"
        )
        cooler_on = cooler_on_val if cooler_on_val is not None else False

        cooler_power = self._client.get_number_nowait(
            self._device_name, "CCD_COOLER_POWER", "CCD_COOLER_VALUE"
        )

        return CameraStatus(
            state=self._state,
            temperature=temperature,
            cooler_on=cooler_on,
            cooler_power=cooler_power,
        )

    async def push_scope_info(self, focal_length: float, aperture: float) -> None:
        """Push telescope optics to the camera's SCOPE_INFO property (best-effort)."""
        try:
            await self._client.set_number(
                self._device_name,
                "SCOPE_INFO",
                {"FOCAL_LENGTH": focal_length, "APERTURE": aperture},
            )
            logger.info(
                "indi.camera_scope_info_pushed",
                device=self._device_name,
                focal_length=focal_length,
                aperture=aperture,
            )
        except Exception as exc:
            logger.debug(
                "indi.camera_scope_info_skipped",
                device=self._device_name,
                error=str(exc),
            )

    async def push_telescope_coord(self, ra_jnow: float, dec_jnow: float) -> None:
        """Push current mount pointing to the camera's TELESCOPE_EOD_COORD property.

        Called before each exposure so the camera's internal FITS writer records the
        correct pointing coordinates.  Best-effort: silently skipped if the driver
        does not expose this property.
        """
        try:
            await self._client.set_number(
                self._device_name,
                "TELESCOPE_EOD_COORD",
                {"RA": ra_jnow, "DEC": dec_jnow},
            )
            logger.debug(
                "indi.camera_telescope_coord_pushed",
                device=self._device_name,
                ra_jnow=ra_jnow,
                dec_jnow=dec_jnow,
            )
        except Exception as exc:
            logger.debug(
                "indi.camera_telescope_coord_skipped",
                device=self._device_name,
                error=str(exc),
            )

    async def set_cooler(self, enabled: bool, target_temperature: float | None) -> None:
        """Enable/disable the cooler and optionally set the target temperature."""
        try:
            await self._client.set_switch(
                self._device_name,
                "CCD_COOLER",
                ["COOLER_ON"] if enabled else ["COOLER_OFF"],
            )
        except Exception as exc:
            logger.debug("indi.camera_cooler_switch_skipped", device=self._device_name, error=str(exc))
        if target_temperature is not None:
            try:
                await self._client.set_number(
                    self._device_name,
                    "CCD_TEMPERATURE",
                    {"CCD_TEMPERATURE_VALUE": float(target_temperature)},
                )
            except Exception as exc:
                logger.debug("indi.camera_temperature_set_skipped", device=self._device_name, error=str(exc))

    async def ping(self) -> bool:
        try:
            await self._client.wait_for_property(
                self._device_name, "CONNECTION", timeout=3.0
            )
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _read_dimensions(self) -> tuple[int, int]:
        try:
            w = await self._client.get_number(self._device_name, "CCD_INFO", "CCD_MAX_X")
            h = await self._client.get_number(self._device_name, "CCD_INFO", "CCD_MAX_Y")
            return int(w), int(h)
        except Exception:
            return 0, 0

    async def get_pixel_size_um(self) -> float | None:
        """Return the physical pixel size in µm from CCD_INFO, or None if unavailable."""
        try:
            return float(await self._client.get_number(self._device_name, "CCD_INFO", "CCD_PIXEL_SIZE"))
        except Exception:
            return None

    async def set_upload_local(self, upload_dir: Path) -> None:
        """Switch the INDI driver to UPLOAD_LOCAL mode for the next exposure.

        The driver will write the FITS file directly to *upload_dir* instead of
        sending it as a base64 BLOB over TCP.  Call restore_upload_client() after
        the exposure so other INDI clients (e.g. PHD2 guide camera) continue to
        receive BLOBs normally.
        """
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w.-]", "_", self._device_name)
        prefix = f"{safe_name}_"
        try:
            await self._client.set_text(
                self._device_name,
                "UPLOAD_SETTINGS",
                {"UPLOAD_DIR": str(upload_dir), "UPLOAD_PREFIX": prefix},
            )
            await self._client.set_switch(
                self._device_name, "UPLOAD_MODE", ["UPLOAD_LOCAL"]
            )
            self._current_upload_dir = upload_dir
            logger.info(
                "indi.camera_local_upload_enabled",
                device=self._device_name,
                upload_dir=str(upload_dir),
                prefix=prefix,
            )
        except Exception as exc:
            logger.warning(
                "indi.camera_local_upload_failed",
                device=self._device_name,
                error=str(exc),
            )

    async def restore_upload_client(self) -> None:
        """Restore UPLOAD_MODE to CLIENT after a local-mode exposure."""
        self._current_upload_dir = None
        try:
            await self._client.set_switch(
                self._device_name, "UPLOAD_MODE", ["UPLOAD_CLIENT"]
            )
        except Exception as exc:
            logger.warning(
                "indi.camera_upload_restore_failed",
                device=self._device_name,
                error=str(exc),
            )
