"""
Stellarium telescope server protocol.

Implements the binary TCP protocol used by Stellarium's Telescope Control
plugin ("3rd party software or remote" → TCP connection).

Wire format (all fields little-endian):

  Server → Stellarium  (CurrentPosition, 24 bytes every ~500 ms):
    uint16  length  = 24
    uint16  type    = 0
    int64   time_us          (microseconds — Stellarium ignores this)
    uint32  ra_int           (0 .. 2^32  maps to  0° .. 360°)
    int32   dec_int          (−2^30 .. +2^30  maps to  −90° .. +90°)
    int32   status  = 0

  Stellarium → Server  (Goto, 20 bytes):
    uint16  length  = 20
    uint16  type    = 0
    int64   time_us
    uint32  ra_int
    int32   dec_int

Coordinates are J2000 (ICRS), matching astrolol's internal representation.
Note: MountStatus.ra is in decimal *hours*; multiply by 15 to get degrees.
"""
from __future__ import annotations

import asyncio
import struct
import time
from typing import Any

import structlog

logger = structlog.get_logger()

_PUSH_INTERVAL = 0.5          # seconds between position updates to each client
_GOTO_PACKET_SIZE = 20        # bytes
_POSITION_PACKET_SIZE = 24    # bytes


# ── Packet helpers ────────────────────────────────────────────────────────────

def _encode_position(ra_hours: float, dec_deg: float) -> bytes:
    """Build a 24-byte CurrentPosition packet."""
    ra_deg = ra_hours * 15.0
    time_us = int(time.time() * 1e6)
    ra_int = int(ra_deg / 360.0 * (1 << 32)) & 0xFFFFFFFF
    dec_int = int(dec_deg / 90.0 * (1 << 30))
    return struct.pack("<HHqIii", _POSITION_PACKET_SIZE, 0, time_us, ra_int, dec_int, 0)


def _decode_goto(data: bytes) -> tuple[float, float] | None:
    """Decode a 20-byte Goto packet → (ra_hours, dec_deg), or None if malformed."""
    if len(data) < _GOTO_PACKET_SIZE:
        return None
    length, type_, _time_us, ra_int, dec_int = struct.unpack_from("<HHqIi", data)
    if length != _GOTO_PACKET_SIZE or type_ != 0:
        return None
    ra_deg = ra_int / (1 << 32) * 360.0
    dec_deg = dec_int / (1 << 30) * 90.0
    return ra_deg / 15.0, dec_deg  # convert RA to hours


# ── Server ────────────────────────────────────────────────────────────────────

class StellariumServer:
    """
    Asyncio TCP server that speaks Stellarium's binary telescope protocol.

    Each connected client receives a position-push task that broadcasts
    the mount's current RA/Dec at _PUSH_INTERVAL.  Goto packets from the
    client are decoded and forwarded to the mount via MountManager.
    """

    def __init__(
        self,
        port: int,
        device_manager: Any,
        mount_manager: Any,
    ) -> None:
        self._port = port
        self._dm = device_manager
        self._mm = mount_manager
        self._server: asyncio.Server | None = None
        self._client_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    @property
    def client_count(self) -> int:
        return sum(1 for t in self._client_tasks if not t.done())

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self._port
        )
        logger.info("stellarium.server_started", port=self._port)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        for task in list(self._client_tasks):
            if not task.done():
                task.cancel()
        if self._client_tasks:
            await asyncio.gather(*self._client_tasks, return_exceptions=True)
        self._client_tasks.clear()
        logger.info("stellarium.server_stopped")

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        logger.info("stellarium.client_connected", peer=str(peer))

        task = asyncio.current_task()
        assert task is not None
        self._client_tasks.add(task)

        # Start a background task that pushes position every _PUSH_INTERVAL
        push_task = asyncio.create_task(self._push_position(writer))

        buf = b""
        try:
            while True:
                chunk = await reader.read(256)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= _GOTO_PACKET_SIZE:
                    length = struct.unpack_from("<H", buf)[0]
                    if len(buf) < length:
                        break
                    packet = buf[:length]
                    buf = buf[length:]
                    await self._handle_goto(packet)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            logger.warning("stellarium.client_error", peer=str(peer), error=str(exc))
        finally:
            push_task.cancel()
            try:
                await push_task
            except asyncio.CancelledError:
                pass
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            self._client_tasks.discard(task)
            logger.info("stellarium.client_disconnected", peer=str(peer))

    async def _push_position(self, writer: asyncio.StreamWriter) -> None:
        """Send the current mount position to this client every _PUSH_INTERVAL."""
        while True:
            await asyncio.sleep(_PUSH_INTERVAL)
            mount_id = self._first_mount_id()
            if mount_id is None:
                # No mount — send zeroes so Stellarium still shows a reticle
                ra_hours, dec_deg = 0.0, 0.0
            else:
                try:
                    status = await self._mm.get_status(mount_id)
                    ra_hours = status.ra or 0.0
                    dec_deg = status.dec or 0.0
                except Exception:
                    ra_hours, dec_deg = 0.0, 0.0

            try:
                writer.write(_encode_position(ra_hours, dec_deg))
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError):
                break

    async def _handle_goto(self, packet: bytes) -> None:
        """Decode a Goto packet and slew the mount."""
        coords = _decode_goto(packet)
        if coords is None:
            return
        ra_hours, dec_deg = coords

        mount_id = self._first_mount_id()
        if mount_id is None:
            logger.warning("stellarium.goto_no_mount")
            return

        try:
            from astropy.coordinates import SkyCoord
            import astropy.units as u
            coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg, frame="icrs")
            await self._mm.set_target(mount_id, coord, source="stellarium")
            await self._mm.slew(mount_id)
            logger.info(
                "stellarium.goto",
                mount_id=mount_id,
                ra_hours=round(ra_hours, 4),
                dec_deg=round(dec_deg, 4),
            )
        except ValueError as exc:
            logger.warning("stellarium.goto_rejected", error=str(exc))
        except Exception as exc:
            logger.warning("stellarium.goto_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _first_mount_id(self) -> str | None:
        for entry in self._dm.list_connected():
            if entry["kind"] == "mount" and entry["state"] == "connected":
                return entry["device_id"]
        return None
