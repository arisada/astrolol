"""
LX200 telescope control server.

Implements the subset of the Meade LX200 ASCII protocol used for
planetarium-software telescope control over TCP.

Compatible with: Stellarium, SkySafari, Cartes du Ciel, TheSkyX,
Voyager, StarryNight, and any other app that supports the LX200 protocol.

Protocol reference (Appendix A of the Meade handbox manual):
  :GR#            → HH:MM:SS#   (current RA, J2000/ICRS)
  :GD#            → ±DD:MM:SS#  (current Dec, J2000/ICRS)
  :Sr HH:MM:SS#   → 1           (set target RA)
  :Sd ±DD:MM:SS#  → 1           (set target Dec)
  :MS#            → 0           (slew to target — two-step with :Sr/:Sd)
  :CM#            → Synced#     (sync mount to current target coords)
  :Q#             →             (abort slew, no response)
  :U#             →             (toggle low/high precision, no response)
  :P#             → HIGH PRECISION / LOW  PRECISION
  :GVP#           → astrolol#   (product name)
  :GW#            → AT2#        (telescope status — always Alt-Az tracking)

Each connected client gets independent state (pending RA/Dec for the
two-step GoTo sequence).  The server always operates on the first
connected mount reported by DeviceManager.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from astrolol.devices.manager import DeviceManager
    from astrolol.mount.manager import MountManager

logger = structlog.get_logger()


# ── Coordinate helpers ────────────────────────────────────────────────────────

def _ra_to_lx200(ra_hours: float, high_precision: bool = True) -> str:
    """Format RA decimal hours as LX200 string."""
    if high_precision:
        total_s = round(ra_hours * 3600) % 86400
        h = total_s // 3600
        m = (total_s % 3600) // 60
        s = total_s % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        h = int(ra_hours) % 24
        m_frac = (ra_hours - int(ra_hours)) * 60
        return f"{h:02d}:{m_frac:04.1f}"


def _dec_to_lx200(dec_deg: float, high_precision: bool = True) -> str:
    """Format Dec decimal degrees as LX200 string."""
    sign = "+" if dec_deg >= 0 else "-"
    abs_deg = abs(dec_deg)
    if high_precision:
        d = int(abs_deg)
        m_frac = (abs_deg - d) * 60
        m = int(m_frac)
        s = round((m_frac - m) * 60)
        if s == 60:
            s = 0
            m += 1
        if m == 60:
            m = 0
            d += 1
        return f"{sign}{d:02d}:{m:02d}:{s:02d}"
    else:
        d = int(abs_deg)
        m = round((abs_deg - d) * 60)
        if m == 60:
            m = 0
            d += 1
        return f"{sign}{d:02d}:{m:02d}"


def _parse_ra(value: str) -> float | None:
    """Parse HH:MM:SS or HH:MM.T to decimal hours."""
    try:
        parts = value.strip().split(":")
        if len(parts) == 3:
            return float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
        if len(parts) == 2:
            return float(parts[0]) + float(parts[1]) / 60
        return None
    except (ValueError, IndexError):
        return None


def _parse_dec(value: str) -> float | None:
    """Parse ±DD:MM:SS or ±DD:MM to decimal degrees."""
    try:
        value = value.strip()
        sign = -1.0 if value.startswith("-") else 1.0
        value = value.lstrip("+-")
        parts = value.split(":")
        if len(parts) == 3:
            deg = float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
        elif len(parts) == 2:
            deg = float(parts[0]) + float(parts[1]) / 60
        else:
            return None
        return sign * deg
    except (ValueError, IndexError):
        return None


# ── Per-connection state ──────────────────────────────────────────────────────

class _ClientState:
    """Mutable state scoped to a single client connection."""

    def __init__(self) -> None:
        self.pending_ra: float | None = None   # decimal hours  (J2000)
        self.pending_dec: float | None = None  # decimal degrees (J2000)
        self.high_precision: bool = True


# ── Server ────────────────────────────────────────────────────────────────────

class Lx200Server:
    """Asyncio TCP server implementing the LX200 telescope control protocol."""

    def __init__(
        self,
        port: int,
        device_manager: Any,   # DeviceManager
        mount_manager: Any,    # MountManager
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
        logger.info("lx200.server_started", port=self._port)

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
        logger.info("lx200.server_stopped")

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        logger.info("lx200.client_connected", peer=str(peer))
        state = _ClientState()
        task = asyncio.current_task()
        assert task is not None
        self._client_tasks.add(task)
        buf = b""
        try:
            while True:
                chunk = await reader.read(512)
                if not chunk:
                    break
                buf += chunk
                while b"#" in buf:
                    idx = buf.index(b"#")
                    raw = buf[:idx].decode("ascii", errors="ignore").strip()
                    buf = buf[idx + 1:]
                    if not raw:
                        continue
                    response = await self._dispatch(raw, state)
                    if response:
                        writer.write(response.encode("ascii"))
                        await writer.drain()
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            logger.warning("lx200.client_error", peer=str(peer), error=str(exc))
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            self._client_tasks.discard(task)
            logger.info("lx200.client_disconnected", peer=str(peer))

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, raw: str, state: _ClientState) -> str:
        """Process one LX200 command (without trailing #) and return the response."""
        if not raw.startswith(":"):
            return ""
        cmd = raw[1:]  # strip leading ':'

        # ── Get current RA ────────────────────────────────────────────
        if cmd == "GR":
            mount_id = self._first_mount_id()
            if mount_id is None:
                return "00:00:00#"
            try:
                status = await self._mm.get_status(mount_id)
                ra = status.ra or 0.0
            except Exception:
                ra = 0.0
            return _ra_to_lx200(ra, state.high_precision) + "#"

        # ── Get current Dec ───────────────────────────────────────────
        if cmd == "GD":
            mount_id = self._first_mount_id()
            if mount_id is None:
                return "+00:00:00#"
            try:
                status = await self._mm.get_status(mount_id)
                dec = status.dec or 0.0
            except Exception:
                dec = 0.0
            return _dec_to_lx200(dec, state.high_precision) + "#"

        # ── Set target RA ─────────────────────────────────────────────
        if cmd.startswith("Sr"):
            val = cmd[2:].strip()
            ra = _parse_ra(val)
            if ra is None:
                return "0"
            state.pending_ra = ra
            return "1"

        # ── Set target Dec ────────────────────────────────────────────
        if cmd.startswith("Sd"):
            val = cmd[2:].strip()
            dec = _parse_dec(val)
            if dec is None:
                return "0"
            state.pending_dec = dec
            return "1"

        # ── Slew to target ────────────────────────────────────────────
        # Response: "0" = slew started, "2" = no target, "1<msg>#" = error
        if cmd == "MS":
            mount_id = self._first_mount_id()
            if mount_id is None:
                return "1No mount connected#"
            if state.pending_ra is None or state.pending_dec is None:
                return "2"
            try:
                from astropy.coordinates import SkyCoord
                import astropy.units as u
                coord = SkyCoord(
                    ra=state.pending_ra * u.hourangle,
                    dec=state.pending_dec * u.deg,
                    frame="icrs",
                )
                await self._mm.set_target(mount_id, coord, source="lx200")
                await self._mm.slew(mount_id)
            except ValueError as exc:
                return f"1{exc}#"
            except Exception as exc:
                logger.warning("lx200.slew_failed", error=str(exc))
                return f"1{exc}#"
            return "0"

        # ── Sync to target ────────────────────────────────────────────
        # Response: a string ending with '#' (traditionally the RA of the
        # synced position; "Synced#" is widely accepted by planetarium apps)
        if cmd == "CM":
            mount_id = self._first_mount_id()
            if mount_id is None:
                return "No mount#"
            if state.pending_ra is None or state.pending_dec is None:
                return "No target set#"
            try:
                from astropy.coordinates import SkyCoord
                import astropy.units as u
                coord = SkyCoord(
                    ra=state.pending_ra * u.hourangle,
                    dec=state.pending_dec * u.deg,
                    frame="icrs",
                )
                await self._mm.sync(mount_id, coord)
            except Exception as exc:
                logger.warning("lx200.sync_failed", error=str(exc))
                return "Sync failed#"
            return "Synced#"

        # ── Abort slew ────────────────────────────────────────────────
        # Spec says no response.
        if cmd == "Q" or cmd.startswith("Q"):
            mount_id = self._first_mount_id()
            if mount_id is not None:
                try:
                    await self._mm.stop(mount_id)
                except Exception:
                    pass
            return ""

        # ── Precision toggle ──────────────────────────────────────────
        # :U# — toggle, no response
        # :P# — toggle and return new mode
        if cmd == "U":
            state.high_precision = not state.high_precision
            return ""
        if cmd == "P":
            state.high_precision = not state.high_precision
            return "HIGH PRECISION#" if state.high_precision else "LOW  PRECISION#"

        # ── Identification ────────────────────────────────────────────
        if cmd == "GVP":
            return "astrolol#"
        if cmd == "GVF":
            return "astrolol|1.0#"
        if cmd in ("GVD", "GVT", "GVN"):
            return "Apr 20 2026#"

        # ── Telescope status ──────────────────────────────────────────
        # AT2 = Alt-Az mount, tracking at sidereal rate, 2-star aligned
        if cmd == "GW":
            return "AT2#"

        # Unrecognised — return empty; many apps probe with unknown commands
        logger.debug("lx200.unknown_command", cmd=cmd)
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _first_mount_id(self) -> str | None:
        """Return the device_id of the first connected mount, or None."""
        for entry in self._dm.list_connected():
            if entry["kind"] == "mount" and entry["state"] == "connected":
                return entry["device_id"]
        return None
