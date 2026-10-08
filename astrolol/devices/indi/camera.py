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
import time
from pathlib import Path

import astropy.io.fits as astropy_fits
import numpy as np
import structlog

from astrolol.config.settings import settings
from astrolol.devices.base.models import (
    CameraStatus,
    DeviceState,
    ExposureParams,
    Image,
)
from astrolol.devices.base.pulse import PulseDirection
from astrolol.devices.base.streaming import (
    Frame,
    FrameBroadcaster,
    FrameSubscription,
    StreamNotSupported,
    StreamParams,
)
from astrolol.devices.indi.client import IndiClient
from astrolol.devices.indi.pulse import indi_pulse_guide

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
        self._broadcaster = FrameBroadcaster()
        self._stream_params: StreamParams | None = None
        self._stream_seq = 0
        self._stream_bad_size_logged = False

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
        if self._stream_params is not None:
            raise RuntimeError("camera is streaming: stop the stream before exposing")
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

        # Reset CCD_FRAME to full sensor dimensions before every exposure.
        # The ZWO ASI SDK applies internal alignment when binning changes and can
        # silently reduce the frame width (e.g. 5496 → 5472). Explicitly restoring
        # the full frame prevents that drift from accumulating in ~/.indi/ and
        # producing images with inconsistent X dimensions across sessions.
        try:
            max_x = await self._client.get_number(self._device_name, "CCD_INFO", "CCD_MAX_X")
            max_y = await self._client.get_number(self._device_name, "CCD_INFO", "CCD_MAX_Y")
            await self._client.set_number(
                self._device_name,
                "CCD_FRAME",
                {"X": 0.0, "Y": 0.0, "WIDTH": float(max_x), "HEIGHT": float(max_y)},
            )
        except Exception as exc:
            logger.debug(
                "indi.camera_frame_reset_skipped",
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

        # Read actual dimensions from the FITS header — these reflect what the
        # driver truly captured, not the theoretical sensor maximum.
        try:
            width, height = await asyncio.to_thread(self._dims_from_fits, fits_path)
        except Exception:
            width, height = 0, 0

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

    # ------------------------------------------------------------------
    # IStreamingCamera: the driver's own video stream (CCD_VIDEO_STREAM)
    # ------------------------------------------------------------------

    def subscribe_frames(self) -> FrameSubscription:
        return self._broadcaster.subscribe()

    @property
    def can_stream(self) -> bool:
        return self._client._get_vector(self._device_name, "CCD_VIDEO_STREAM") is not None

    async def start_stream(self, params: StreamParams) -> None:
        """Start the driver's raw video stream.

        A region of interest is applied by the driver (CCD_STREAM_FRAME), so far fewer bytes
        travel to us than full frames: for guiding, always pass one once a star is chosen.
        """
        if not self.can_stream:
            raise StreamNotSupported(f"{self._device_name} has no CCD_VIDEO_STREAM")
        if self._stream_params is not None:
            raise RuntimeError("already streaming")
        dev, client = self._device_name, self._client
        if params.gain is not None:
            await self._best_effort("gain", client.set_number(dev, "CCD_GAIN", {"GAIN": float(params.gain)}))
        await self._best_effort(
            "binning",
            client.set_number(dev, "CCD_BINNING", {"HOR_BIN": float(params.binning), "VER_BIN": float(params.binning)}),
        )
        await self._best_effort("encoder", client.set_switch(dev, "CCD_STREAM_ENCODER", ["RAW"]))
        if params.roi is not None:
            r = params.roi
            frame = {"X": float(r.x), "Y": float(r.y), "WIDTH": float(r.width), "HEIGHT": float(r.height)}
        else:
            max_x = await client.get_number(dev, "CCD_INFO", "CCD_MAX_X")
            max_y = await client.get_number(dev, "CCD_INFO", "CCD_MAX_Y")
            frame = {"X": 0.0, "Y": 0.0, "WIDTH": float(max_x) // params.binning, "HEIGHT": float(max_y) // params.binning}
        await self._best_effort("stream frame", client.set_number(dev, "CCD_STREAM_FRAME", frame))
        await client.set_number(dev, "STREAMING_EXPOSURE", {"STREAMING_EXPOSURE_VALUE": params.exposure})

        self._stream_params = params
        self._stream_seq = 0
        self._stream_bad_size_logged = False
        client.add_blob_listener(dev, "CCD1", self._on_stream_blob)
        try:
            await client.enable_blob(dev)
            await client.set_switch(dev, "CCD_VIDEO_STREAM", ["STREAM_ON"])
        except Exception:
            client.remove_blob_listener(dev, "CCD1", self._on_stream_blob)
            self._stream_params = None
            raise
        self._state = DeviceState.BUSY
        logger.info("indi.camera_stream_started", device=dev, exposure=params.exposure)

    async def stop_stream(self) -> None:
        params, self._stream_params = self._stream_params, None
        if params is None:
            return
        dev, client = self._device_name, self._client
        client.remove_blob_listener(dev, "CCD1", self._on_stream_blob)
        try:
            await self._best_effort("stream off", client.set_switch(dev, "CCD_VIDEO_STREAM", ["STREAM_OFF"]))
            await self._best_effort("blob off", client.disable_blob(dev))
        finally:
            self._broadcaster.end()
            self._state = DeviceState.CONNECTED
        logger.info("indi.camera_stream_stopped", device=dev, frames=self._stream_seq)

    def _on_stream_blob(self, data: bytes, fmt: str) -> None:
        params = self._stream_params
        if params is None:
            return
        client, dev = self._client, self._device_name
        width = client.get_number_nowait(dev, "CCD_STREAM_FRAME", "WIDTH")
        height = client.get_number_nowait(dev, "CCD_STREAM_FRAME", "HEIGHT")
        if not width or not height or len(data) % int(width * height) != 0:
            if not self._stream_bad_size_logged:  # one line, not one per frame
                self._stream_bad_size_logged = True
                logger.warning("indi.camera_stream_bad_frame", device=dev, size=len(data), width=width, height=height, format=fmt)
            return
        w, h = int(width), int(height)
        bytes_per_pixel = len(data) // (w * h)
        if bytes_per_pixel not in (1, 2):
            if not self._stream_bad_size_logged:
                self._stream_bad_size_logged = True
                logger.warning("indi.camera_stream_unsupported_depth", device=dev, bytes_per_pixel=bytes_per_pixel, format=fmt)
            return
        pixels = np.frombuffer(data, dtype=np.uint8 if bytes_per_pixel == 1 else "<u2").reshape(h, w)
        self._stream_seq += 1
        self._broadcaster.publish(
            Frame(
                pixels=pixels,
                seq=self._stream_seq,
                timestamp=time.monotonic(),
                exposure=params.exposure,
                gain=params.gain,
                binning=params.binning,
                origin=(
                    int(client.get_number_nowait(dev, "CCD_STREAM_FRAME", "X") or 0),
                    int(client.get_number_nowait(dev, "CCD_STREAM_FRAME", "Y") or 0),
                ),
            )
        )

    async def _best_effort(self, what: str, call) -> None:  # noqa: ANN001
        try:
            await call
        except Exception as exc:
            logger.debug("indi.camera_stream_setting_skipped", device=self._device_name, setting=what, error=str(exc))

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
        """Push current mount pointing to the camera's TELESCOPE_EOD_COORD property,
        for drivers that expose a directly-writable coordinate property instead of (or
        in addition to) ACTIVE_DEVICES snooping. Best-effort: silently skipped if the
        driver does not expose this property -- confirmed a no-op on indi_simulator_ccd,
        which relies on set_active_telescope's snoop mechanism instead, but some real
        camera drivers may implement this property, so both are pushed.
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

    async def set_active_telescope(self, telescope_device_name: str) -> None:
        """Point the camera driver's own ACTIVE_DEVICES.ACTIVE_TELESCOPE snoop at the
        given INDI device name, so the driver's native snoop mechanism picks up live
        mount coordinates for FITS header pointing and (for simulators) star-field
        rendering. Best-effort: silently skipped if the driver has no such property.
        """
        try:
            await self._client.set_text(
                self._device_name,
                "ACTIVE_DEVICES",
                {"ACTIVE_TELESCOPE": telescope_device_name},
            )
            logger.debug(
                "indi.camera_active_telescope_set",
                device=self._device_name,
                telescope_device_name=telescope_device_name,
            )
        except Exception as exc:
            logger.debug(
                "indi.camera_active_telescope_skipped",
                device=self._device_name,
                error=str(exc),
            )

    async def pulse_guide(self, direction: PulseDirection, duration_ms: int) -> None:
        """Timed guide pulse through the camera's ST4 output, for cameras that have one."""
        await indi_pulse_guide(self._client, self._device_name, direction, duration_ms)

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

    @staticmethod
    def _dims_from_fits(fits_path: Path) -> tuple[int, int]:
        with astropy_fits.open(str(fits_path)) as hdul:
            hdr = hdul[0].header
            return int(hdr["NAXIS1"]), int(hdr["NAXIS2"])

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
