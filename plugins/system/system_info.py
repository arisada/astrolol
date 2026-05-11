"""System information via psutil and /sys filesystem."""
from __future__ import annotations

import asyncio
import socket
import time
from pathlib import Path

import psutil
import structlog

from plugins.system.models import SystemStatus

logger = structlog.get_logger()

_THERMAL_PATHS = [
    Path("/sys/class/thermal/thermal_zone0/temp"),
    Path("/sys/class/hwmon/hwmon0/temp1_input"),
]


def _read_temperature() -> float | None:
    """Read CPU temperature from /sys (millidegrees → degrees Celsius)."""
    for path in _THERMAL_PATHS:
        try:
            raw = int(path.read_text().strip())
            # Values above 1000 are in millidegrees; below are already Celsius
            return raw / 1000.0 if raw > 1000 else float(raw)
        except (OSError, ValueError):
            continue

    # Fallback: psutil sensors (Linux only)
    try:
        temps = psutil.sensors_temperatures()
        for group in ("coretemp", "cpu_thermal", "soc_thermal", "acpitz"):
            if group in temps and temps[group]:
                return temps[group][0].current
    except (AttributeError, OSError):
        pass

    return None


async def get_system_status() -> SystemStatus:
    """Collect CPU, memory, disk, temperature, and uptime statistics."""
    # cpu_percent(interval) blocks; run in a thread pool to avoid stalling the loop
    cpu = await asyncio.get_event_loop().run_in_executor(
        None, lambda: psutil.cpu_percent(interval=0.2)
    )

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = psutil.boot_time()
    uptime = time.time() - boot_time
    hostname = socket.gethostname()
    temperature = _read_temperature()

    try:
        import platform as _platform
        platform_str = _platform.machine() or "unknown"
    except Exception:
        platform_str = "unknown"

    return SystemStatus(
        cpu_percent=round(cpu, 1),
        memory_percent=round(mem.percent, 1),
        memory_used_mb=round(mem.used / 1024 / 1024, 1),
        memory_total_mb=round(mem.total / 1024 / 1024, 1),
        disk_percent=round(disk.percent, 1),
        disk_used_gb=round(disk.used / 1024 / 1024 / 1024, 2),
        disk_total_gb=round(disk.total / 1024 / 1024 / 1024, 2),
        temperature_celsius=round(temperature, 1) if temperature is not None else None,
        uptime_seconds=round(uptime, 0),
        hostname=hostname,
        platform=platform_str,
    )
