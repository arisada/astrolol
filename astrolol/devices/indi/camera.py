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
        exposure_timeout_extra: float = 30.0,
    ) -> None:
        self._device_name = device_name
        self._client = client
        self._images_dir = images_dir or settings.images_dir
        self._exposure_timeout_extra = exposure_timeout_extra
        self._state = DeviceState.DISCONNECTED
        self._image_counter = 0

    # ------------------------------------------------------------------
    # ICamera protocol
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._state = DeviceState.CONNECTING
        try:
            await self._client.connect_device(self._device_name)
            await self._client.enable_blob(self._device_name)
            self._state = DeviceState.CONNECTED
        except Exception:
            self._state = DeviceState.ERROR
            raise

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect_device(self._device_name)
        finally:
            self._state = DeviceState.DISCONNECTED

    async def expose(self, params: ExposureParams) -> Image:
        self._state = DeviceState.BUSY

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
        if params.gain != 0:
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

        # Trigger exposure
        await self._client.set_number(
            self._device_name,
            "CCD_EXPOSURE",
            {"CCD_EXPOSURE_VALUE": params.duration},
        )

        # Wait for BLOB (image data)
        timeout = params.duration + self._exposure_timeout_extra
        blob = await self._client.wait_for_blob(self._device_name, timeout=timeout)

        # Save to FITS
        self._images_dir.mkdir(parents=True, exist_ok=True)
        self._image_counter += 1
        fits_path = self._images_dir / f"frame_{self._image_counter:06d}.fits"

        def _save() -> None:
            with open(fits_path, "wb") as f:
                f.write(bytes(blob.getblobdata()))

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
            await self._client.set_number(
                self._device_name, "CCD_ABORT_EXPOSURE", {"ABORT": 1.0}
            )
        except Exception as exc:
            logger.warning("indi.camera_abort_failed", device=self._device_name, error=str(exc))
        finally:
            self._state = DeviceState.CONNECTED

    async def get_status(self) -> CameraStatus:
        temperature: float | None = None
        cooler_on = False
        cooler_power: float | None = None

        try:
            temperature = await self._client.get_number(
                self._device_name, "CCD_TEMPERATURE", "CCD_TEMPERATURE_VALUE"
            )
        except Exception:
            pass

        try:
            cooler_on = await self._client.get_switch_state(
                self._device_name, "CCD_COOLER", "COOLER_ON"
            )
        except Exception:
            pass

        try:
            cooler_power = await self._client.get_number(
                self._device_name, "CCD_COOLER_POWER", "CCD_COOLER_VALUE"
            )
        except Exception:
            pass

        return CameraStatus(
            state=self._state,
            temperature=temperature,
            cooler_on=cooler_on,
            cooler_power=cooler_power,
        )

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
