"""
Alpaca camera adapter — implements ICamera (and pulse guiding through the camera's ST4 port).

Alpaca returns pixels, not a file: the adapter writes the FITS itself, with the headers an INDI
driver would have put there (exposure, binning, gain, temperature, pixel size, Bayer pattern).
"""
from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from astropy.io import fits

from astrolol.config.settings import settings
from astrolol.plugins.alpaca.base import AlpacaDevice
from astrolol.plugins.alpaca.client import AlpacaError, AlpacaNotImplemented
from astrolol.plugins.alpaca.pulse import alpaca_pulse_guide
from astrolol.devices.base.models import CameraStatus, DeviceState, ExposureParams, Image
from astrolol.devices.base.pulse import PulseDirection, PulseGuideNotSupported

logger = structlog.get_logger()

# SensorType: 0 monochrome, 1 colour (one plane per colour), 2 RGGB, 3 CMYG, 4 CMYG2, 5 LRGB.
_BAYER_PATTERNS = {2: "RGGB", 3: "CMYG", 4: "CMYG", 5: "LRGB"}
# CameraState: 0 idle, 1 waiting, 2 exposing, 3 reading, 4 download, 5 error.
_CAMERA_ERROR = 5

_files = itertools.count(1)


class AlpacaCamera(AlpacaDevice):
    """ICamera backed by an Alpaca Camera device."""

    ADAPTER_KEY = "alpaca_camera"
    DEVICE_TYPE = "camera"
    DEFAULT_CONNECT_PARAMS = dict(AlpacaDevice.DEFAULT_CONNECT_PARAMS)

    def __init__(self, *args: Any, images_dir: Path | None = None,
                 exposure_timeout_extra: float = 60.0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._images_dir = Path(images_dir) if images_dir else settings.images_dir
        self._exposure_timeout_extra = exposure_timeout_extra
        self._caps: dict[str, Any] = {}

    async def _on_connected(self) -> None:
        a = self._alpaca
        self._caps = {
            "width": int(await a.get("cameraxsize")),
            "height": int(await a.get("cameraysize")),
            "max_bin": int(await a.get_or("maxbinx", 1)),
            "pixel_size": await a.get_or("pixelsizex", None),
            "sensor_type": int(await a.get_or("sensortype", 0)),
            "bayer_x": int(await a.get_or("bayeroffsetx", 0)),
            "bayer_y": int(await a.get_or("bayeroffsety", 0)),
            "max_adu": int(await a.get_or("maxadu", 65535)),
            "can_abort": bool(await a.get_or("canabortexposure", False)),
            "can_stop": bool(await a.get_or("canstopexposure", False)),
            "can_pulse": bool(await a.get_or("canpulseguide", False)),
            "can_cooler_power": bool(await a.get_or("cangetcoolerpower", False)),
            "can_set_temperature": bool(await a.get_or("cansetccdtemperature", False)),
            "has_gain": await a.get_or("gainmax", None) is not None,
        }

    # ------------------------------------------------------------------
    # ICamera
    # ------------------------------------------------------------------

    async def expose(self, params: ExposureParams) -> Image:
        a, caps = self._alpaca, self._caps
        self._state = DeviceState.BUSY
        try:
            binning = max(1, min(params.binning, caps["max_bin"]))
            await a.put("binx", BinX=binning)
            await a.put("biny", BinY=binning)
            await a.put("startx", StartX=0)
            await a.put("starty", StartY=0)
            await a.put("numx", NumX=caps["width"] // binning)
            await a.put("numy", NumY=caps["height"] // binning)
            if params.gain is not None and caps["has_gain"]:
                await a.put("gain", Gain=params.gain)
            light = params.frame_type not in ("dark", "bias")
            started = datetime.now(timezone.utc)
            await a.put("startexposure", Duration=params.duration, Light=light)
            try:
                await self._wait_until(self._image_ready, params.duration + self._exposure_timeout_extra,
                                       "exposure", interval=min(0.5, max(0.05, params.duration / 4)))
            except asyncio.CancelledError:
                await self.abort()
                raise
            pixels = await a.image_array()
            fits_path = await asyncio.to_thread(
                self._write_fits, pixels, params, binning, started,
                await a.get_or("ccdtemperature", None),
                await a.get_or("gain", None) if caps["has_gain"] else None,
            )
        finally:
            self._state = DeviceState.CONNECTED
        logger.info("alpaca.camera_exposure_done", device=repr(a), fits=str(fits_path), duration=params.duration)
        return Image(fits_path=str(fits_path), width=pixels.shape[1], height=pixels.shape[0],
                     exposure_duration=params.duration)

    async def _image_ready(self) -> bool:
        if await self._alpaca.get("imageready"):
            return True
        if await self._alpaca.get_or("camerastate", 0) == _CAMERA_ERROR:
            raise AlpacaError("camera reports an exposure error")
        return False

    def _write_fits(self, pixels: np.ndarray, params: ExposureParams, binning: int,
                    started: datetime, temperature: float | None, gain: int | None) -> Path:
        caps = self._caps
        if pixels.ndim == 3:   # colour planes: FITS wants planes first
            pixels = np.moveaxis(pixels, 2, 0)
        if np.issubdtype(pixels.dtype, np.integer):
            data = pixels.astype(np.uint16) if caps["max_adu"] <= 65535 and pixels.min() >= 0 else pixels.astype(np.int32)
        else:
            data = pixels.astype(np.float32)
        hdu = fits.PrimaryHDU(data)
        h = hdu.header
        h["EXPTIME"] = (params.duration, "[s] Exposure duration")
        h["DATE-OBS"] = (started.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3], "UTC start of the exposure")
        h["XBINNING"] = (binning, "Binning factor in width")
        h["YBINNING"] = (binning, "Binning factor in height")
        if caps["pixel_size"]:
            h["XPIXSZ"] = (float(caps["pixel_size"]) * binning, "[um] Pixel width, binned")
            h["YPIXSZ"] = (float(caps["pixel_size"]) * binning, "[um] Pixel height, binned")
        if gain is not None:
            h["GAIN"] = (gain, "Sensor gain")
        if temperature is not None:
            h["CCD-TEMP"] = (float(temperature), "[C] Sensor temperature")
        if self.name:
            h["INSTRUME"] = (self.name, "Camera")
        h["ROWORDER"] = ("TOP-DOWN", "Row order of the image data")
        pattern = _BAYER_PATTERNS.get(caps["sensor_type"])
        if pattern and binning == 1 and pixels.ndim == 2:
            h["BAYERPAT"] = (pattern, "Bayer colour pattern")
            h["XBAYROFF"] = (caps["bayer_x"], "Bayer pattern X offset")
            h["YBAYROFF"] = (caps["bayer_y"], "Bayer pattern Y offset")
        self._images_dir.mkdir(parents=True, exist_ok=True)
        path = self._images_dir / f"alpaca_camera{self._alpaca.device_number}_{next(_files):06d}.fits"
        hdu.writeto(path, overwrite=True)
        return path

    async def abort(self) -> None:
        a, caps = self._alpaca, self._caps
        try:
            if caps.get("can_abort"):
                await a.put("abortexposure")
            elif caps.get("can_stop"):
                await a.put("stopexposure")
        except AlpacaError as exc:
            logger.warning("alpaca.camera_abort_failed", device=repr(a), error=str(exc))
        finally:
            self._state = DeviceState.CONNECTED

    async def get_status(self) -> CameraStatus:
        a = self._alpaca
        if self._state not in (DeviceState.CONNECTED, DeviceState.BUSY):
            return CameraStatus(state=self._state)
        try:
            temperature = await a.get_or("ccdtemperature", None)
            cooler_on = bool(await a.get_or("cooleron", False))
            power = await a.get_or("coolerpower", None) if self._caps.get("can_cooler_power") else None
        except AlpacaError as exc:
            logger.debug("alpaca.camera_status_failed", device=repr(a), error=str(exc))
            return CameraStatus(state=self._state)
        return CameraStatus(state=self._state, temperature=temperature, cooler_on=cooler_on,
                            cooler_power=power)

    async def set_cooler(self, enabled: bool, target_temperature: float | None) -> None:
        a = self._alpaca
        try:
            await a.put("cooleron", CoolerOn=enabled)
        except AlpacaNotImplemented:
            logger.debug("alpaca.camera_no_cooler", device=repr(a))
            return
        if target_temperature is not None and self._caps.get("can_set_temperature"):
            await a.put("setccdtemperature", SetCCDTemperature=float(target_temperature))

    async def pulse_guide(self, direction: PulseDirection, duration_ms: int) -> None:
        """Timed guide pulse through the camera's ST4 output, for cameras that have one."""
        if not self._caps.get("can_pulse"):
            raise PulseGuideNotSupported(f"{self.name or 'camera'} has no guide output")
        await alpaca_pulse_guide(self._alpaca, direction, duration_ms)

    async def get_pixel_size_um(self) -> float | None:
        size = self._caps.get("pixel_size")
        return float(size) if size else None
