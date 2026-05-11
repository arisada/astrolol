"""FastAPI router for the system management plugin."""
from __future__ import annotations

import asyncio
import os
import sys

import structlog
from fastapi import APIRouter, HTTPException, Request

from plugins.system import network as _net
from plugins.system import system_info as _si
from plugins.system.models import (
    HotspotStartRequest,
    NetworkStatus,
    SudoSetup,
    SystemSettings,
    SystemStatus,
    WifiConnectRequest,
    WifiNetwork,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/system", tags=["system"])

_PLUGIN_KEY = "system"


def _settings(request: Request) -> SystemSettings:
    raw = request.app.state.profile_store.get_user_settings().plugin_settings.get(_PLUGIN_KEY, {})
    return SystemSettings(**raw)


def _save_settings(request: Request, s: SystemSettings) -> None:
    store = request.app.state.profile_store
    current = store.get_user_settings()
    updated = {**current.plugin_settings, _PLUGIN_KEY: s.model_dump()}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))


# ── System status ──────────────────────────────────────────────────────────────

@router.get("/status", response_model=SystemStatus)
async def get_system_status() -> SystemStatus:
    """Return CPU, memory, disk, temperature, and uptime."""
    return await _si.get_system_status()


# ── Network ────────────────────────────────────────────────────────────────────

@router.get("/network", response_model=NetworkStatus)
async def get_network_status() -> NetworkStatus:
    """Return current network mode, SSID, and IP addresses."""
    return await _net.get_network_status()


@router.get("/network/scan", response_model=list[WifiNetwork])
async def scan_wifi(request: Request) -> list[WifiNetwork]:
    """Scan for available WiFi networks. May take a couple of seconds."""
    s = _settings(request)
    return await _net.scan_wifi(interface=s.hotspot_interface or None)


@router.post("/network/connect", status_code=200)
async def connect_wifi(body: WifiConnectRequest, request: Request) -> dict[str, str]:
    """Connect to a WiFi network."""
    s = _settings(request)
    try:
        await _net.connect_wifi(
            ssid=body.ssid,
            password=body.password,
            interface=body.interface or s.hotspot_interface or None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "connected", "ssid": body.ssid}


@router.post("/network/disconnect", status_code=200)
async def disconnect_wifi(request: Request) -> dict[str, str]:
    """Disconnect from the current WiFi network."""
    s = _settings(request)
    try:
        await _net.disconnect_wifi(interface=s.hotspot_interface or None)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "disconnected"}


@router.post("/network/hotspot/start", status_code=200)
async def start_hotspot(body: HotspotStartRequest, request: Request) -> dict[str, str]:
    """Start a WiFi access point (hotspot/AP mode)."""
    s = _settings(request)
    ssid = body.ssid or s.hotspot_ssid
    password = body.password or s.hotspot_password
    interface = body.interface or s.hotspot_interface or None

    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Hotspot password must be at least 8 characters")

    try:
        await _net.start_hotspot(ssid=ssid, password=password, interface=interface)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "hotspot_active", "ssid": ssid}


@router.post("/network/hotspot/stop", status_code=200)
async def stop_hotspot() -> dict[str, str]:
    """Stop the WiFi hotspot and return to station mode."""
    try:
        await _net.stop_hotspot()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "hotspot_stopped"}


# ── Settings ───────────────────────────────────────────────────────────────────

@router.get("/settings", response_model=SystemSettings)
async def get_settings(request: Request) -> SystemSettings:
    return _settings(request)


@router.put("/settings", response_model=SystemSettings)
async def put_settings(body: SystemSettings, request: Request) -> SystemSettings:
    _save_settings(request, body)
    return body


# ── Sudo / capabilities ────────────────────────────────────────────────────────

@router.get("/sudo", response_model=SudoSetup)
async def get_sudo_setup() -> SudoSetup:
    """Check which privileged operations are available."""
    perms = await _net.check_sudo_permissions()
    username = os.environ.get("USER", "pi")
    setup_commands = [
        f"echo '{username} ALL=(ALL) NOPASSWD: /usr/bin/nmcli' | sudo tee /etc/sudoers.d/astrolol-nmcli",
        f"echo '{username} ALL=(ALL) NOPASSWD: /sbin/reboot' | sudo tee /etc/sudoers.d/astrolol-reboot",
        f"echo '{username} ALL=(ALL) NOPASSWD: /sbin/shutdown' | sudo tee /etc/sudoers.d/astrolol-shutdown",
        "sudo chmod 440 /etc/sudoers.d/astrolol-*",
    ]
    return SudoSetup(
        nmcli_sudo_ok=perms.get("nmcli", False),
        reboot_sudo_ok=perms.get("reboot", False),
        shutdown_sudo_ok=perms.get("shutdown", False),
        setup_commands=setup_commands,
    )


# ── Power controls ─────────────────────────────────────────────────────────────

@router.post("/reboot", status_code=202)
async def reboot_system() -> dict[str, str]:
    """Reboot the host system. Requires passwordless sudo for /sbin/reboot."""
    async def _do() -> None:
        await asyncio.sleep(0.5)
        logger.info("system.rebooting")
        proc = await asyncio.create_subprocess_exec("sudo", "reboot")
        await proc.wait()

    asyncio.create_task(_do())
    return {"status": "rebooting"}


@router.post("/shutdown", status_code=202)
async def shutdown_system() -> dict[str, str]:
    """Shut down the host system. Requires passwordless sudo for /sbin/shutdown."""
    async def _do() -> None:
        await asyncio.sleep(0.5)
        logger.info("system.shutting_down")
        proc = await asyncio.create_subprocess_exec("sudo", "shutdown", "-h", "now")
        await proc.wait()

    asyncio.create_task(_do())
    return {"status": "shutting_down"}


@router.post("/restart", status_code=202)
async def restart_astrolol() -> dict[str, str]:
    """Restart the astrolol process (same as /admin/restart)."""
    async def _do() -> None:
        await asyncio.sleep(0.3)
        logger.info("system.restarting_astrolol")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    asyncio.create_task(_do())
    return {"status": "restarting"}
