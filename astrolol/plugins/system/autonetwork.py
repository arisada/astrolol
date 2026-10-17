"""Automatic Wi-Fi / hotspot choice.

At home the computer joins a known Wi-Fi network; in the field, where none is in range, it
opens its own hotspot. Decisions are made here rather than by NetworkManager's autoconnect,
which would happily start the hotspot before the boot-time scan has found the home network.

Rules (policy "auto"):
  * For ``boot_wifi_window_seconds`` after boot the hotspot is never started by this watchdog,
    so a known network always gets its chance — a way in if the hotspot ever breaks.
  * No connection after that (Wi-Fi or Ethernet): start the hotspot.
  * A connection that is lost while running: wait ``lost_wifi_grace_seconds`` first.
Policy "wifi" never starts it; policy "hotspot" starts it as soon as the boot window is over.
A hotspot the user stopped by hand is not restarted until the policy changes (or, in "auto",
until a connection has been seen again).
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import structlog

from astrolol.plugins.system import network as _net
from astrolol.plugins.system.models import NetworkMode, NetworkPolicy, NetworkStatus, SystemSettings

logger = structlog.get_logger()

_POLL_SECONDS = 5.0
_RETRY_SECONDS = 30.0


def system_uptime() -> float:
    """Seconds since the computer booted (falls back to 0 where /proc/uptime is missing)."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


class NetworkWatchdog:
    def __init__(
        self,
        get_settings: Callable[[], SystemSettings],
        *,
        status_fn: Callable[[], Awaitable[NetworkStatus]] = _net.get_network_status,
        ethernet_fn: Callable[[], Awaitable[bool]] = _net.ethernet_connected,
        start_hotspot_fn: Callable[..., Awaitable[None]] = _net.start_hotspot,
        clock: Callable[[], float] = time.monotonic,
        uptime_fn: Callable[[], float] = system_uptime,
    ) -> None:
        self._get_settings = get_settings
        self._status = status_fn
        self._ethernet = ethernet_fn
        self._start_hotspot = start_hotspot_fn
        self._clock = clock
        self._uptime = uptime_fn
        self._task: asyncio.Task[None] | None = None
        self._policy: NetworkPolicy | None = None
        self._suppressed = False
        self._had_connection = False
        self._lost_since: float | None = None
        self._retry_at = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="system_network_watchdog")

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        try:
            while True:
                try:
                    await self.tick()
                except Exception:  # noqa: BLE001 — a watchdog must outlive any single failure
                    logger.error("system.network_watchdog_failed", exc_info=True)
                await asyncio.sleep(_POLL_SECONDS)
        except asyncio.CancelledError:
            pass

    # ── manual control ───────────────────────────────────────────────────────

    def suppress(self) -> None:
        """The user stopped the hotspot by hand: do not start it again on our own."""
        self._suppressed = True

    # ── decision ─────────────────────────────────────────────────────────────

    async def tick(self) -> None:
        cfg = self._get_settings()
        if self._policy is not None and cfg.network_policy != self._policy:
            self._suppressed = False
        self._policy = cfg.network_policy

        st = await self._status()
        if not st.nmcli_available or st.interface is None:
            return

        now = self._clock()
        hotspot_up = st.mode == NetworkMode.hotspot
        connected = st.mode == NetworkMode.wifi or await self._ethernet()

        if connected:
            self._had_connection = True
            self._lost_since = None
            if cfg.network_policy == NetworkPolicy.auto:
                self._suppressed = False
        elif hotspot_up:
            self._lost_since = None
        elif self._lost_since is None:
            self._lost_since = now

        if cfg.network_policy == NetworkPolicy.wifi or self._suppressed or hotspot_up:
            return
        if self._uptime() < cfg.boot_wifi_window_seconds:
            return
        if cfg.network_policy == NetworkPolicy.auto:
            if connected:
                return
            grace = cfg.lost_wifi_grace_seconds if self._had_connection else 0
            if self._lost_since is not None and now - self._lost_since < grace:
                return
        if now < self._retry_at:
            return

        logger.info("system.hotspot_auto_start", policy=cfg.network_policy.value)
        try:
            await self._start_hotspot(
                ssid=cfg.hotspot_ssid,
                password=cfg.hotspot_password,
                interface=cfg.hotspot_interface or None,
            )
        except RuntimeError as exc:
            self._retry_at = now + _RETRY_SECONDS
            logger.warning("system.hotspot_auto_start_failed", error=str(exc))
