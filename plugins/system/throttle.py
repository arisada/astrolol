"""Raspberry Pi power/thermal throttling detection and periodic monitoring.

Reads the firmware throttling bitmask, preferring ``vcgencmd get_throttled``
and falling back to the ``get_throttled`` sysfs attribute exposed by the
raspberrypi-hwmon kernel driver. Bit layout (see the official vcgencmd docs):

  bit 0  — under-voltage detected (now)
  bit 1  — arm frequency capped (now)
  bit 2  — currently throttled (now)
  bit 3  — soft temperature limit active (now)
  bit 16 — under-voltage has occurred since boot
  bit 17 — arm frequency capping has occurred since boot
  bit 18 — throttling has occurred since boot
  bit 19 — soft temperature limit has occurred since boot
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from plugins.system.models import ThrottleStatus

logger = structlog.get_logger()

# Known locations of the raspberrypi-hwmon sysfs attribute; differs by SoC
# (device-tree bus layout changed between Pi 3 and Pi 4/5).
_SYSFS_CANDIDATES = [
    Path("/sys/devices/platform/soc/soc:firmware/get_throttled"),
    Path("/sys/devices/platform/axi/scb/soc/soc:firmware/get_throttled"),
]

# Sentinel distinguishing "not searched yet" from "searched, found nothing"
_UNSEARCHED = object()
_sysfs_path_cache: Path | None | object = _UNSEARCHED


def _find_sysfs_path() -> Path | None:
    global _sysfs_path_cache
    if _sysfs_path_cache is not _UNSEARCHED:
        return _sysfs_path_cache  # type: ignore[return-value]

    for candidate in _SYSFS_CANDIDATES:
        if candidate.exists():
            _sysfs_path_cache = candidate
            return candidate

    try:
        match = next(Path("/sys/devices/platform").rglob("get_throttled"), None)
    except OSError:
        match = None
    _sysfs_path_cache = match
    return match


def _parse_bits(raw_hex: str) -> ThrottleStatus:
    try:
        bits = int(raw_hex, 16)
    except ValueError:
        bits = 0
    under_voltage = bool(bits & (1 << 0))
    freq_capped = bool(bits & (1 << 1))
    throttled = bool(bits & (1 << 2))
    soft_temp_limit = bool(bits & (1 << 3))
    return ThrottleStatus(
        available=True,
        source="",  # filled in by caller
        raw_hex=raw_hex,
        under_voltage=under_voltage,
        freq_capped=freq_capped,
        throttled=throttled,
        soft_temp_limit=soft_temp_limit,
        under_voltage_occurred=bool(bits & (1 << 16)),
        freq_capped_occurred=bool(bits & (1 << 17)),
        throttled_occurred=bool(bits & (1 << 18)),
        soft_temp_limit_occurred=bool(bits & (1 << 19)),
        underpowered=under_voltage or freq_capped or throttled or soft_temp_limit,
    )


_UNAVAILABLE = ThrottleStatus(
    available=False,
    source="unavailable",
    raw_hex=None,
    under_voltage=False,
    freq_capped=False,
    throttled=False,
    soft_temp_limit=False,
    under_voltage_occurred=False,
    freq_capped_occurred=False,
    throttled_occurred=False,
    soft_temp_limit_occurred=False,
    underpowered=False,
)


async def get_throttle_status() -> ThrottleStatus:
    """Return the current firmware throttling status.

    Prefers the raspberrypi-hwmon sysfs attribute — a plain file read, no
    process spawn — and falls back to ``vcgencmd get_throttled`` (which pays
    fork/exec overhead for the same underlying firmware mailbox query) when
    the sysfs attribute isn't present, e.g. in a container without the driver
    mapped in, or a system without vcgencmd's kernel module loaded.
    """
    loop = asyncio.get_event_loop()
    path = await loop.run_in_executor(None, _find_sysfs_path)
    if path is not None:
        try:
            text = await loop.run_in_executor(None, path.read_text)
        except OSError:
            text = None
        if text and text.strip():
            status = _parse_bits(text.strip())
            return status.model_copy(update={"source": "sysfs"})

    try:
        proc = await asyncio.create_subprocess_exec(
            "vcgencmd", "get_throttled",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            _, _, val = stdout.decode().strip().partition("=")
            if val:
                status = _parse_bits(val.strip())
                return status.model_copy(update={"source": "vcgencmd"})
    except FileNotFoundError:
        pass

    return _UNAVAILABLE


_ISSUE_LABELS = (
    ("under_voltage", "under-voltage"),
    ("throttled", "throttled"),
    ("freq_capped", "arm frequency capped"),
    ("soft_temp_limit", "soft temperature limit"),
)


class ThrottleMonitor:
    """Periodically polls the throttling status and warns in the logs on power/thermal issues."""

    def __init__(self, *, enabled: bool = True, interval_seconds: float = 30.0) -> None:
        self._enabled = enabled
        self._interval = float(interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._was_underpowered = False
        self.last_status: ThrottleStatus | None = None

    async def start(self) -> None:
        if not self._enabled or (self._task is not None and not self._task.done()):
            return
        self._task = asyncio.create_task(self._poll_loop(), name="system_throttle_monitor")

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def apply_settings(self, *, enabled: bool, interval_seconds: float) -> None:
        """Reconfigure and restart the poll loop with new settings."""
        await self.stop()
        self._enabled = enabled
        self._interval = float(interval_seconds)
        await self.start()

    async def _poll_loop(self) -> None:
        try:
            while True:
                await self.check_once()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass

    async def check_once(self) -> ThrottleStatus:
        status = await get_throttle_status()
        self.last_status = status

        if status.available:
            if status.underpowered and not self._was_underpowered:
                issues = [label for attr, label in _ISSUE_LABELS if getattr(status, attr)]
                logger.warning(
                    "system.underpowered_detected",
                    raw_throttled=status.raw_hex,
                    issues=", ".join(issues),
                    source=status.source,
                )
            elif not status.underpowered and self._was_underpowered:
                logger.info("system.underpowered_cleared", raw_throttled=status.raw_hex)
            self._was_underpowered = status.underpowered

        return status
