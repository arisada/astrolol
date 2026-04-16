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
        pre_connect_props: dict | None = None,
        exposure_timeout_extra: float = 30.0,
    ) -> None:
        self._device_name = device_name
        self._client = client
        self._pre_connect_props = pre_connect_props
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
            await self._client.connect_device(
                self._device_name,
                pre_connect_props=self._pre_connect_props,
            )
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

        # Wait for BLOB (image data) — arrives on the CCD1 property
        timeout = params.duration + self._exposure_timeout_extra
        blob = await self._client.wait_for_blob(self._device_name, "CCD1", timeout=timeout)

        # Save to FITS
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

        temperature = self._client.get_number_nowait(
            self._device_name, "CCD_TEMPERATURE", "CCD_TEMPERATURE_VALUE"
        )

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
