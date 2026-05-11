"""System information via psutil and /sys filesystem."""
from __future__ import annotations

import asyncio
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
import structlog

from plugins.system.models import HostnameInfo, StorageDisk, SystemStatus, TimeInfo

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


async def get_storage_disks() -> list[StorageDisk]:
    """Return all mounted physical/meaningful partitions with usage stats."""
    _SKIP_TYPES = frozenset({"tmpfs", "devtmpfs", "devfs", "overlay", "aufs", "squashfs", "proc",
                              "sysfs", "cgroup", "cgroup2", "pstore", "debugfs", "tracefs",
                              "securityfs", "bpf", "hugetlbfs", "mqueue", "nsfs", "fusectl"})
    result: list[StorageDisk] = []
    for part in psutil.disk_partitions(all=False):
        if part.fstype in _SKIP_TYPES:
            continue
        if not part.mountpoint:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        removable = (
            part.mountpoint.startswith("/media")
            or part.mountpoint.startswith("/mnt")
            or "usb" in part.device.lower()
            or "sd" in part.device.lower() and part.mountpoint != "/"
        )
        result.append(StorageDisk(
            device=part.device,
            mountpoint=part.mountpoint,
            filesystem=part.fstype,
            total_gb=round(usage.total / 1024 ** 3, 2),
            used_gb=round(usage.used / 1024 ** 3, 2),
            free_gb=round(usage.free / 1024 ** 3, 2),
            percent=round(usage.percent, 1),
            removable=removable,
        ))
    return sorted(result, key=lambda d: d.mountpoint)


async def get_time_info() -> TimeInfo:
    """Return current time, timezone, and NTP sync status via timedatectl."""
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now().astimezone()

    timezone_name = str(now_local.tzinfo) if now_local.tzinfo else "UTC"
    ntp_synced = False
    ntp_active = False
    rtc_time: str | None = None

    # Try timedatectl for authoritative NTP info
    try:
        proc = await asyncio.create_subprocess_exec(
            "timedatectl", "show", "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            for line in stdout.decode().splitlines():
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if key == "Timezone":
                    timezone_name = val
                elif key == "NTPSynchronized":
                    ntp_synced = val.lower() == "yes"
                elif key == "NTP":
                    ntp_active = val.lower() == "yes"
                elif key == "RTCTimeUSec" and val:
                    rtc_time = val
    except FileNotFoundError:
        pass  # timedatectl not available (non-systemd system)

    return TimeInfo(
        datetime_local=now_local.isoformat(timespec="seconds"),
        datetime_utc=now_utc.isoformat(timespec="seconds"),
        timezone=timezone_name,
        ntp_synced=ntp_synced,
        ntp_service_active=ntp_active,
        rtc_time=rtc_time,
    )


async def get_available_timezones() -> list[str]:
    """Return list of available timezone names from timedatectl."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "timedatectl", "list-timezones",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return [tz.strip() for tz in stdout.decode().splitlines() if tz.strip()]
    except FileNotFoundError:
        pass
    # Fallback: common timezone list
    return [
        "UTC", "Europe/London", "Europe/Paris", "Europe/Brussels", "Europe/Berlin",
        "Europe/Madrid", "Europe/Rome", "Europe/Athens", "Europe/Helsinki",
        "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
        "America/Sao_Paulo", "America/Buenos_Aires",
        "Asia/Tokyo", "Asia/Seoul", "Asia/Shanghai", "Asia/Singapore", "Asia/Kolkata",
        "Asia/Dubai", "Asia/Istanbul",
        "Australia/Sydney", "Australia/Melbourne",
        "Pacific/Auckland", "Pacific/Honolulu",
        "Africa/Cairo", "Africa/Johannesburg",
    ]


async def get_hostname_info() -> HostnameInfo:
    """Return current hostname and FQDN."""
    hostname = socket.gethostname()
    try:
        fqdn: str | None = socket.getfqdn()
        if fqdn == hostname:
            fqdn = None
    except Exception:
        fqdn = None
    return HostnameInfo(hostname=hostname, fqdn=fqdn)


async def set_hostname(new_hostname: str) -> None:
    """Change the system hostname via hostnamectl. Requires sudo."""
    proc = await asyncio.create_subprocess_exec(
        "sudo", "hostnamectl", "set-hostname", new_hostname,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode().strip() or f"hostnamectl exited {proc.returncode}")


async def set_timezone(tz: str) -> None:
    """Set system timezone via timedatectl. Requires sudo."""
    proc = await asyncio.create_subprocess_exec(
        "sudo", "timedatectl", "set-timezone", tz,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode().strip() or f"timedatectl exited {proc.returncode}")
