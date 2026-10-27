"""Network management via nmcli (NetworkManager CLI).

All shell commands run with asyncio.create_subprocess_exec for non-blocking
operation. nmcli runs as astrolol's own user: NetworkManager asks polkit, and
deploy/50-astrolol.rules allows the changes (see privileges.py).

The module degrades gracefully when nmcli is not present or polkit refuses —
callers receive an error detail rather than an exception crash.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import structlog

from astrolol.plugins.system.models import NetworkMode, NetworkStatus, SavedWifiConnection, WifiNetwork

logger = structlog.get_logger()

_HOTSPOT_CON_NAME = "astrolol-hotspot"
# Fixed so clients (and bookmarks) always find the Pi at the same address.
_HOTSPOT_ADDRESS = "10.42.0.1/24"


def split_terse(line: str) -> list[str]:
    """Split a ``nmcli -t`` line on unescaped ':' (nmcli escapes ':' and '\\' in values)."""
    parts: list[str] = []
    cur: list[str] = []
    it = iter(line)
    for ch in it:
        if ch == "\\":
            cur.append(next(it, ""))
        elif ch == ":":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def nmcli_available() -> bool:
    return shutil.which("nmcli") is not None


async def _run(*args: str) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    cmd = list(args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: command not found"
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


async def detect_wifi_interface() -> str | None:
    """Return the first wireless interface found via nmcli, or None."""
    if not nmcli_available():
        return None
    rc, out, _ = await _run("nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status")
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = split_terse(line)
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return None


async def _wifi_profile(name: str) -> tuple[str | None, str | None]:
    """Return (mode, ssid) of a Wi-Fi connection profile ("infrastructure", "ap", …)."""
    rc, out, _ = await _run(
        "nmcli", "-t", "-f", "802-11-wireless.mode,802-11-wireless.ssid", "connection", "show", name
    )
    if rc != 0:
        return None, None
    mode: str | None = None
    ssid: str | None = None
    for line in out.splitlines():
        key, _, value = line.partition(":")
        value = split_terse(value)[0].strip() if value else ""
        if key == "802-11-wireless.mode":
            mode = value or None
        elif key == "802-11-wireless.ssid":
            ssid = value or None
    return mode, ssid


async def ethernet_connected() -> bool:
    """True when a wired interface is connected (the host is reachable without Wi-Fi)."""
    if not nmcli_available():
        return False
    rc, out, _ = await _run("nmcli", "-t", "-f", "TYPE,STATE", "device", "status")
    if rc != 0:
        return False
    for line in out.splitlines():
        parts = split_terse(line)
        if len(parts) >= 2 and parts[0] == "ethernet" and parts[1] == "connected":
            return True
    return False


async def get_network_status() -> NetworkStatus:
    """Parse current network state from nmcli."""
    if not nmcli_available():
        return NetworkStatus(
            mode=NetworkMode.unknown,
            interface=None,
            ssid=None,
            ip_address=None,
            gateway=None,
            hotspot_ssid=None,
            hotspot_ip=None,
            nmcli_available=False,
        )

    interface = await detect_wifi_interface()

    # Check active connections
    rc, out, _ = await _run(
        "nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"
    )
    active_ssid: str | None = None
    is_hotspot = False
    hotspot_ssid: str | None = None

    if rc == 0:
        for line in out.splitlines():
            parts = split_terse(line)
            if len(parts) < 3:
                continue
            name, conn_type = parts[0], parts[1]
            if conn_type != "802-11-wireless":
                continue
            wifi_mode, ssid = await _wifi_profile(name)
            if name == _HOTSPOT_CON_NAME or wifi_mode == "ap":
                is_hotspot = True
                hotspot_ssid = ssid or (name if name != _HOTSPOT_CON_NAME else None)
            else:
                active_ssid = name

    # Determine mode
    if is_hotspot:
        mode = NetworkMode.hotspot
    elif active_ssid:
        mode = NetworkMode.wifi
    elif interface:
        mode = NetworkMode.disconnected
    else:
        mode = NetworkMode.unknown

    # Get IP info for the wireless interface
    ip_address: str | None = None
    gateway: str | None = None
    hotspot_ip: str | None = None

    if interface:
        rc, dev_out, _ = await _run(
            "nmcli", "-t", "-f", "IP4.ADDRESS,IP4.GATEWAY", "device", "show", interface
        )
        if rc == 0:
            for line in dev_out.splitlines():
                if line.startswith("IP4.ADDRESS"):
                    raw = line.split(":", 1)[-1].strip()
                    # strip CIDR prefix
                    ip_address = raw.split("/")[0] if raw else None
                elif line.startswith("IP4.GATEWAY"):
                    val = line.split(":", 1)[-1].strip()
                    gateway = val if val and val != "--" else None

        if is_hotspot:
            hotspot_ip = ip_address
            ip_address = None

    return NetworkStatus(
        mode=mode,
        interface=interface,
        ssid=active_ssid,
        ip_address=ip_address,
        gateway=gateway,
        hotspot_ssid=hotspot_ssid,
        hotspot_ip=hotspot_ip,
        nmcli_available=True,
    )


async def scan_wifi(interface: str | None = None) -> list[WifiNetwork]:
    """Scan for available WiFi networks. Returns deduplicated list by SSID."""
    if not nmcli_available():
        return []

    iface = interface or await detect_wifi_interface()
    args = ["nmcli", "--terse", "-f", "SSID,BSSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"]
    if iface:
        args += ["ifname", iface]

    rc, out, err = await _run(*args)
    if rc != 0:
        logger.warning("system.wifi_scan_failed", error=err)
        return []

    seen_ssids: set[str] = set()
    results: list[WifiNetwork] = []

    for line in out.splitlines():
        # nmcli -t separates fields with ":"; BSSIDs contain ":" too, so
        # the format is SSID:BSSID_part1:BSSID_part2:...:SIGNAL:SECURITY:IN-USE
        # Use regex to match the BSSID pattern instead of naive split.
        m = re.match(
            r"^(.*?):([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}):(\d+):(.*?):(\*?)$",
            line,
        )
        if not m:
            continue
        ssid = m.group(1).strip()
        bssid = m.group(2)
        signal = int(m.group(3))
        security = m.group(4).strip() or "Open"
        in_use = m.group(5) == "*"

        if not ssid or ssid == "--":
            continue
        if ssid in seen_ssids:
            # Keep the strongest signal entry
            existing = next((n for n in results if n.ssid == ssid), None)
            if existing and signal > existing.signal:
                results.remove(existing)
            else:
                continue

        seen_ssids.add(ssid)
        results.append(WifiNetwork(ssid=ssid, bssid=bssid, signal=signal, security=security, in_use=in_use))

    return sorted(results, key=lambda n: -n.signal)


async def connect_wifi(ssid: str, password: str, interface: str | None = None) -> None:
    """Connect to a WiFi network. Raises RuntimeError on failure."""
    if not nmcli_available():
        raise RuntimeError("nmcli not available — NetworkManager is required")

    iface = interface or await detect_wifi_interface()
    args = ["nmcli", "device", "wifi", "connect", ssid, "password", password]
    if iface:
        args += ["ifname", iface]

    logger.info("system.wifi_connecting", ssid=ssid, interface=iface)
    rc, out, err = await _run(*args)
    if rc != 0:
        logger.error("system.wifi_connect_failed", ssid=ssid, error=err or out)
        raise RuntimeError(err or out or f"nmcli exited {rc}")
    logger.info("system.wifi_connected", ssid=ssid)


async def disconnect_wifi(interface: str | None = None) -> None:
    """Disconnect from the current WiFi network."""
    if not nmcli_available():
        raise RuntimeError("nmcli not available")

    iface = interface or await detect_wifi_interface()
    if not iface:
        raise RuntimeError("No wireless interface found")

    rc, _, err = await _run("nmcli", "device", "disconnect", iface)
    if rc != 0:
        raise RuntimeError(err or f"nmcli exited {rc}")
    logger.info("system.wifi_disconnected", interface=iface)


async def start_hotspot(ssid: str, password: str, interface: str | None = None) -> None:
    """Create and bring up a WiFi access point using NetworkManager.

    Uses a named connection so it can be cleanly stopped later.
    Replaces any previously created astrolol hotspot connection.
    """
    if not nmcli_available():
        raise RuntimeError("nmcli not available — NetworkManager is required")

    iface = interface or await detect_wifi_interface()
    if not iface:
        raise RuntimeError("No wireless interface found")

    # Remove any existing hotspot connection
    await _run("nmcli", "connection", "delete", _HOTSPOT_CON_NAME)

    # Create a new hotspot connection
    rc, out, err = await _run(
        "nmcli", "connection", "add",
        "type", "wifi",
        "ifname", iface,
        "con-name", _HOTSPOT_CON_NAME,
        "autoconnect", "no",
        "ssid", ssid,
        "mode", "ap",
        "802-11-wireless.band", "bg",
        "ipv4.method", "shared",
        "ipv4.addresses", _HOTSPOT_ADDRESS,
        "ipv6.method", "ignore",
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.proto", "rsn",
        "wifi-sec.pairwise", "ccmp",
        "wifi-sec.group", "ccmp",
        "wifi-sec.psk", password,
    )
    if rc != 0:
        logger.error("system.hotspot_create_failed", error=err or out)
        raise RuntimeError(err or out or f"nmcli exited {rc}")

    # Bring it up
    rc, out, err = await _run("nmcli", "connection", "up", _HOTSPOT_CON_NAME)
    if rc != 0:
        logger.error("system.hotspot_start_failed", error=err or out)
        raise RuntimeError(err or out or f"nmcli exited {rc}")

    logger.info("system.hotspot_started", ssid=ssid, interface=iface)


async def stop_hotspot() -> None:
    """Bring down the astrolol hotspot connection."""
    if not nmcli_available():
        raise RuntimeError("nmcli not available")

    rc, _, err = await _run("nmcli", "connection", "down", _HOTSPOT_CON_NAME)
    if rc != 0:
        raise RuntimeError(err or f"nmcli exited {rc}")

    # Clean up the connection profile
    await _run("nmcli", "connection", "delete", _HOTSPOT_CON_NAME)
    logger.info("system.hotspot_stopped")


async def list_saved_wifi_connections() -> list[SavedWifiConnection]:
    """Return saved WiFi connection profiles from NetworkManager."""
    if not nmcli_available():
        return []
    rc, out, _ = await _run(
        "nmcli", "-t", "-f", "NAME,TYPE,DEVICE,AUTOCONNECT", "connection", "show"
    )
    if rc != 0:
        return []
    results: list[SavedWifiConnection] = []
    for line in out.splitlines():
        parts = split_terse(line)
        if len(parts) < 4:
            continue
        name, conn_type, device, autoconnect = parts[0], parts[1], parts[2], parts[3]
        if conn_type != "802-11-wireless":
            continue
        if name == _HOTSPOT_CON_NAME:
            continue  # hide the internal hotspot profile
        results.append(SavedWifiConnection(
            name=name,
            interface=device if device and device != "--" else None,
            autoconnect=autoconnect.strip().lower() == "yes",
        ))
    return results


async def delete_saved_connection(name: str) -> None:
    """Delete a saved NetworkManager connection profile by name."""
    if not nmcli_available():
        raise RuntimeError("nmcli not available")
    rc, _, err = await _run("nmcli", "connection", "delete", name)
    if rc != 0:
        raise RuntimeError(err or f"nmcli exited {rc}")
    logger.info("system.connection_deleted", name=name)
