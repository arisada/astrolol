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


class SudoSetup(BaseModel):
    nmcli_sudo_ok: bool
    reboot_sudo_ok: bool
    shutdown_sudo_ok: bool
    setup_commands: list[str]
