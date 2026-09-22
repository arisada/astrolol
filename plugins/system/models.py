"""Pydantic models for the system management plugin."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class NetworkMode(str, Enum):
    wifi = "wifi"
    hotspot = "hotspot"
    disconnected = "disconnected"
    unknown = "unknown"


class WifiNetwork(BaseModel):
    ssid: str
    bssid: str
    signal: int  # 0–100
    security: str
    in_use: bool = False


class NetworkStatus(BaseModel):
    mode: NetworkMode
    interface: str | None
    ssid: str | None
    ip_address: str | None
    gateway: str | None
    hotspot_ssid: str | None
    hotspot_ip: str | None
    nmcli_available: bool


class SystemStatus(BaseModel):
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    temperature_celsius: float | None
    uptime_seconds: float
    hostname: str
    platform: str


class WifiConnectRequest(BaseModel):
    ssid: str
    password: str
    interface: str | None = None


class HotspotStartRequest(BaseModel):
    ssid: str | None = None
    password: str | None = None
    interface: str | None = None


class SystemSettings(BaseModel):
    hotspot_ssid: str = Field(default="AstroLOL")
    hotspot_password: str = Field(default="astronomy123")
    hotspot_interface: str = Field(default="wlan0")
    throttle_monitor_enabled: bool = Field(default=True)
    # Under-voltage dips are typically brief (a few seconds), so this defaults
    # low — a sysfs read is cheap (no subprocess spawn) and safe to do often.
    throttle_check_interval_seconds: int = Field(default=1, ge=1, le=3600)


class SudoSetup(BaseModel):
    nmcli_sudo_ok: bool
    reboot_sudo_ok: bool
    shutdown_sudo_ok: bool
    setup_commands: list[str]


class TimeInfo(BaseModel):
    datetime_local: str        # ISO 8601 local time
    datetime_utc: str          # ISO 8601 UTC
    timezone: str              # e.g. "Europe/Brussels"
    ntp_synced: bool
    ntp_service_active: bool
    rtc_time: str | None


class StorageDisk(BaseModel):
    device: str
    mountpoint: str
    filesystem: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent: float
    removable: bool


class HostnameInfo(BaseModel):
    hostname: str
    fqdn: str | None


class SetHostnameRequest(BaseModel):
    hostname: str = Field(min_length=1, max_length=63)


class UsbDevice(BaseModel):
    bus: str
    device: str
    vendor_id: str
    product_id: str
    name: str


class SavedWifiConnection(BaseModel):
    name: str
    interface: str | None
    autoconnect: bool


class ThrottleStatus(BaseModel):
    available: bool             # False when neither vcgencmd nor the sysfs file could be read
    source: str                 # "vcgencmd" | "sysfs" | "unavailable"
    raw_hex: str | None         # raw bitmask, e.g. "0x50005"
    under_voltage: bool
    freq_capped: bool
    throttled: bool
    soft_temp_limit: bool
    under_voltage_occurred: bool
    freq_capped_occurred: bool
    throttled_occurred: bool
    soft_temp_limit_occurred: bool
    underpowered: bool          # True if any of the four "now" flags above is set
