"""Async TCP client for PHD2's JSON-RPC 2.0 event-monitoring API.

PHD2 listens on port 4400 (default).  It sends newline-delimited JSON:
  - Events  — JSON objects containing an "Event" key (no "id")
  - Responses — JSON objects containing an "id" key that matches a request

The client maintains a persistent reconnect loop and publishes received events
to the astrolol EventBus so they flow through to WebSocket clients.
"""
from __future__ import annotations

import asyncio
import json
import math
import structlog
from collections import deque
from typing import Any

from astrolol.core.events import EventBus
from plugins.phd2.events import (
    Phd2Connected,
    Phd2Disconnected,
    Phd2GuideStep,
    Phd2StateChanged,
    Phd2Settled,
)
from plugins.phd2.models import Phd2Status

logger = structlog.get_logger()

_RECONNECT_DELAY = 5.0   # seconds between connection attempts
_RPC_TIMEOUT = 10.0      # seconds to wait for a JSON-RPC response
_RMS_WINDOW = 50         # number of guide steps for rolling RMS calculation


def _rms(values: deque[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


class Phd2Client:
    """Persistent, auto-reconnecting client for PHD2's JSON-RPC socket API."""

    def __init__(self, host: str, port: int, event_bus: EventBus) -> None:
        self._host = host
        self._port = port
        self._event_bus = event_bus

        # PHD2 application state
        self._state = "Disconnected"
        self._connected = False
        self._pixel_scale: float | None = None
        self._star_snr: float | None = None
        self._pixel_scale_fetched = False  # True once we've gotten a reliable scale

        # Rolling RMS window (raw guide-camera pixels)
        self._ra_steps: deque[float] = deque(maxlen=_RMS_WINDOW)
        self._dec_steps: deque[float] = deque(maxlen=_RMS_WINDOW)

        # JSON-RPC infrastructure
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._writer: asyncio.StreamWriter | None = None

        # Settle signalling — set by _handle_event when SettleDone arrives
        self._settle_event: asyncio.Event | None = None
        self._settle_error: str | None = None
        self._dithering = False  # True while a dither+settle is in progress

        # Lifecycle
        self._stop = False
        self._task: asyncio.Task[None] | None = None

        # Debug mode — prints raw JSON-RPC traffic to stdout when enabled
        self._debug = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background reconnect loop."""
        self._stop = False
        self._task = asyncio.create_task(self._reconnect_loop(), name="phd2_client")

    async def stop(self) -> None:
        """Stop the reconnect loop and close any open connection."""
        self._stop = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def reconnect(self, host: str | None = None, port: int | None = None) -> None:
        """Stop any existing loop then start a fresh one.

        Pass *host* and/or *port* to change the target before reconnecting.
        """
        if host is not None:
            self._host = host
        if port is not None:
            self._port = port
        await self.stop()
        await self.start()

    def set_debug(self, enabled: bool) -> None:
        """Enable or disable raw JSON-RPC traffic logging to stdout."""
        self._debug = enabled
        state = "enabled" if enabled else "disabled"
        print(f"\033[90mPHD2 debug logging {state}\033[0m", flush=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Phd2Status:
        scale = self._pixel_scale or 1.0
        rms_ra_px = _rms(self._ra_steps) if self._ra_steps else None
        rms_dec_px = _rms(self._dec_steps) if self._dec_steps else None
        rms_ra = rms_ra_px * scale if rms_ra_px is not None else None
        rms_dec = rms_dec_px * scale if rms_dec_px is not None else None
        rms_total = (
            math.sqrt(rms_ra ** 2 + rms_dec ** 2)
            if rms_ra is not None and rms_dec is not None
            else None
        )
        return Phd2Status(
            connected=self._connected,
            state=self._state,
            rms_ra=round(rms_ra, 3) if rms_ra is not None else None,
            rms_dec=round(rms_dec, 3) if rms_dec is not None else None,
            rms_total=round(rms_total, 3) if rms_total is not None else None,
            pixel_scale=self._pixel_scale,
            star_snr=self._star_snr,
            is_dithering=self._dithering,
            debug_enabled=self._debug,
        )

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    async def guide(
        self,
        settle_pixels: float = 1.5,
        settle_time: int = 10,
        settle_timeout: int = 60,
        recalibrate: bool = False,
    ) -> None:
        settle = {"pixels": settle_pixels, "time": settle_time, "timeout": settle_timeout}
        await self._call("guide", [settle, recalibrate])

    async def stop_capture(self) -> None:
        await self._call("stop_capture")

    async def dither(
        self,
        pixels: float = 5.0,
        ra_only: bool = False,
        settle_pixels: float = 1.5,
        settle_time: int = 10,
        settle_timeout: int = 60,
    ) -> None:
        """Send a dither command and block until PHD2 reports SettleDone."""
        if not self._connected:
            raise ConnectionError("Not connected to PHD2")
        if self._dithering:
            raise RuntimeError("Dither already in progress")

        self._dithering = True
        event = asyncio.Event()
        self._settle_event = event
        self._settle_error = None

        try:
            settle = {"pixels": settle_pixels, "time": settle_time, "timeout": settle_timeout}
            await self._call("dither", [pixels, ra_only, settle])
            await asyncio.wait_for(event.wait(), timeout=settle_timeout + 60)
        except asyncio.TimeoutError:
            raise TimeoutError("PHD2 settle timed out")
        finally:
            self._dithering = False
            if self._settle_event is event:
                self._settle_event = None

        if self._settle_error:
            raise RuntimeError(f"PHD2 settle failed: {self._settle_error}")

    async def pause(self) -> None:
        await self._call("pause", [True])

    async def resume(self) -> None:
        await self._call("pause", [False])

    # ------------------------------------------------------------------
    # Internal — reconnect loop
    # ------------------------------------------------------------------

    async def _reconnect_loop(self) -> None:
        while not self._stop:
            try:
                reader, writer = await asyncio.open_connection(self._host, self._port)
                self._writer = writer
                self._connected = True
                self._state = "Unknown"
                logger.info("phd2.connected", host=self._host, port=self._port)
                await self._event_bus.publish(Phd2Connected())

                # Fetch pixel scale and current app state.
                # PHD2 returns 1.0 when the scale is not yet configured/calibrated,
                # so we only treat it as reliable if > 1.0 at connect time.
                try:
                    scale = float(await self._call("get_pixel_scale"))
                    self._pixel_scale = scale
                    self._pixel_scale_fetched = scale > 1.0
                except Exception:
                    pass
                try:
                    self._state = str(await self._call("get_app_state"))
                    await self._event_bus.publish(Phd2StateChanged(state=self._state))
                except Exception:
                    pass

                await self._reader_loop(reader)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.info("phd2.connection_failed", host=self._host, port=self._port, error=str(exc))
            finally:
                self._on_disconnect()

            if not self._stop:
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _refresh_pixel_scale(self) -> None:
        """Re-fetch pixel scale from PHD2 and update the stored value."""
        try:
            scale = float(await self._call("get_pixel_scale"))
            if scale > 0.0:
                self._pixel_scale = scale
                self._pixel_scale_fetched = True
                logger.info("phd2.pixel_scale_updated", pixel_scale=scale)
        except Exception:
            pass

    def _on_disconnect(self) -> None:
        was_connected = self._connected
        self._connected = False
        self._writer = None
        self._state = "Disconnected"
        self._pixel_scale_fetched = False

        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("PHD2 disconnected"))
        self._pending.clear()

        if self._settle_event is not None:
            self._settle_error = "PHD2 disconnected"
            self._settle_event.set()

        if was_connected:
            asyncio.get_event_loop().create_task(
                self._event_bus.publish(Phd2Disconnected())
            )

    async def _reader_loop(self, reader: asyncio.StreamReader) -> None:
        while True:
            try:
                line = await reader.readline()
            except Exception:
                break
            if not line:
                break
            try:
                msg = json.loads(line.decode())
            except json.JSONDecodeError:
                continue

            if self._debug:
                if "Event" in msg:
                    print(f"\033[33mPHD2 ← {json.dumps(msg)}\033[0m", flush=True)
                else:
                    print(f"\033[32mPHD2 ← {json.dumps(msg)}\033[0m", flush=True)

            if "Event" in msg:
                await self._handle_event(msg)
            elif "id" in msg:
                rid = int(msg["id"])
                fut = self._pending.pop(rid, None)
                if fut is not None and not fut.done():
                    if "error" in msg:
                        fut.set_exception(
                            RuntimeError(msg["error"].get("message", "PHD2 RPC error"))
                        )
                    else:
                        fut.set_result(msg.get("result"))

    async def _handle_event(self, msg: dict[str, Any]) -> None:
        event_name = msg.get("Event", "")

        if event_name == "AppState":
            self._state = msg.get("State", "Unknown")
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

        elif event_name == "GuideStep":
            ra_raw = float(msg.get("RADistanceRaw") or 0)
            dec_raw = float(msg.get("DECDistanceRaw") or 0)
            self._ra_steps.append(ra_raw)
            self._dec_steps.append(dec_raw)
            snr = msg.get("SNR")
            self._star_snr = float(snr) if snr is not None else None

            # A GuideStep means the star is being tracked — recover from Star loss
            if self._state == "Star loss":
                self._state = "Guiding"
                await self._event_bus.publish(Phd2StateChanged(state=self._state))

            # If we still don't have a reliable pixel scale (e.g. PHD2 was already
            # guiding when we connected and CalibrationComplete never fired), try
            # once to fetch it now.  The flag prevents a retry on every frame.
            if not self._pixel_scale_fetched:
                asyncio.create_task(self._refresh_pixel_scale())
                self._pixel_scale_fetched = True  # don't retry until next connect

            scale = self._pixel_scale or 1.0
            await self._event_bus.publish(
                Phd2GuideStep(
                    frame=int(msg.get("Frame") or 0),
                    ra_dist=round(ra_raw * scale, 4),
                    dec_dist=round(dec_raw * scale, 4),
                    ra_corr=float(msg.get("RADuration") or 0),
                    dec_corr=float(msg.get("DECDuration") or 0),
                    star_snr=self._star_snr,
                )
            )

        elif event_name == "SettleDone":
            err = msg.get("Error", "")
            self._settle_error = err if err else None
            if self._settle_error:
                logger.warning("phd2.settle_failed", error=self._settle_error)
            else:
                logger.info("phd2.settled")
            if self._settle_event is not None:
                self._settle_event.set()
            await self._event_bus.publish(Phd2Settled(error=self._settle_error))

        elif event_name == "StartGuiding":
            self._state = "Guiding"
            self._ra_steps.clear()
            self._dec_steps.clear()
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

        elif event_name == "GuidingStopped":
            self._state = "Stopped"
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

        elif event_name == "Paused":
            self._state = "Paused"
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

        elif event_name == "Resumed":
            self._state = "Guiding"
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

        elif event_name == "StarLost":
            self._state = "Star loss"
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

        elif event_name == "StarSelected":
            self._state = "Selected"
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

        elif event_name == "CalibrationComplete":
            self._state = "Guiding"
            # Calibration just finished — this is the definitive moment PHD2
            # has a reliable pixel scale, so always re-fetch it.
            await self._refresh_pixel_scale()
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

        elif event_name == "CalibrationFailed":
            self._state = "Stopped"
            await self._event_bus.publish(Phd2StateChanged(state=self._state))

    # ------------------------------------------------------------------
    # Internal — JSON-RPC call
    # ------------------------------------------------------------------

    async def _call(self, method: str, params: Any = None) -> Any:
        if self._writer is None:
            raise ConnectionError("Not connected to PHD2")

        rid = self._next_id
        self._next_id += 1

        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut

        payload: dict[str, Any] = {"method": method, "id": rid}
        if params is not None:
            payload["params"] = params

        if self._debug:
            print(f"\033[36mPHD2 → {json.dumps(payload)}\033[0m", flush=True)

        self._writer.write((json.dumps(payload) + "\r\n").encode())
        await self._writer.drain()

        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=_RPC_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._pending.pop(rid, None)
            raise
