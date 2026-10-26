"""Finding Alpaca servers and their devices.

Discovery (Alpaca's own): a UDP datagram "alpacadiscovery1" to port 32227, broadcast on every
IPv4 network this machine is on, and sent to 127.0.0.1 too (a server on this machine answers
there, and broadcasts do not loop back to it everywhere). Each server answers
``{"AlpacaPort": <port>}`` from its address. Its management API then names it and lists its
devices. A server that broadcasts do not reach (another subnet, a VPN) is asked directly.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket

import httpx
import ifaddr
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

DISCOVERY_PORT = 32227
DISCOVERY_MESSAGE = b"alpacadiscovery1"
DEFAULT_ALPACA_PORT = 11111

# Alpaca device type → (astrolol kind, adapter key). The other types (Dome, Switch,
# SafetyMonitor, ObservingConditions) have no astrolol counterpart yet.
DEVICE_KINDS: dict[str, tuple[str, str]] = {
    "camera": ("camera", "alpaca_camera"),
    "telescope": ("mount", "alpaca_mount"),
    "focuser": ("focuser", "alpaca_focuser"),
    "filterwheel": ("filter_wheel", "alpaca_filter_wheel"),
    "rotator": ("rotator", "alpaca_rotator"),
    "covercalibrator": ("flat_panel", "alpaca_flat_panel"),
}


class AlpacaDeviceInfo(BaseModel):
    name: str
    device_type: str               # Alpaca's: "Camera", "Telescope", …
    device_number: int
    unique_id: str = ""
    kind: str | None = None        # astrolol's device kind; None = not supported
    adapter_key: str | None = None


class AlpacaServerInfo(BaseModel):
    host: str
    port: int
    name: str = ""
    manufacturer: str = ""
    version: str = ""
    location: str = ""
    devices: list[AlpacaDeviceInfo] = []


class AddressError(BaseModel):
    address: str
    error: str


def broadcast_addresses() -> list[str]:
    """Where to send the discovery datagram: each network's broadcast, the global one, and loopback."""
    found: list[str] = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if not ip.is_IPv4 or not isinstance(ip.ip, str) or ip.ip.startswith("127."):
                continue
            try:
                network = ipaddress.IPv4Network(f"{ip.ip}/{ip.network_prefix}", strict=False)
            except ValueError:
                continue
            if network.prefixlen < 32:
                found.append(str(network.broadcast_address))
    return list(dict.fromkeys([*found, "255.255.255.255", "127.0.0.1"]))


class _Collector(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.servers: dict[tuple[str, int], None] = {}

    def datagram_received(self, data: bytes, addr: tuple) -> None:  # type: ignore[override]
        if data == DISCOVERY_MESSAGE:      # our own broadcast, looped back
            return
        try:
            port = int(json.loads(data.decode("utf-8"))["AlpacaPort"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            logger.debug("alpaca.discovery_bad_answer", source=addr[0], data=data[:80])
            return
        self.servers[(addr[0], port)] = None

    def error_received(self, exc: Exception) -> None:
        logger.debug("alpaca.discovery_send_failed", error=str(exc))


async def discover_servers(
    timeout: float = 1.5,
    *,
    addresses: list[str] | None = None,
    port: int | None = None,
) -> list[tuple[str, int]]:
    """(host, Alpaca port) of each server that answers within *timeout* seconds."""
    port = port or DISCOVERY_PORT
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", 0))
    transport, collector = await loop.create_datagram_endpoint(_Collector, sock=sock)
    try:
        for address in addresses if addresses is not None else broadcast_addresses():
            try:
                transport.sendto(DISCOVERY_MESSAGE, (address, port))
            except OSError as exc:
                logger.debug("alpaca.discovery_send_failed", address=address, error=str(exc))
        await asyncio.sleep(timeout)
    finally:
        transport.close()
    return list(collector.servers)


async def describe_server(host: str, port: int, *, timeout: float = 3.0,
                          transport: httpx.AsyncBaseTransport | None = None) -> AlpacaServerInfo:
    """Name and devices of the Alpaca server at host:port (its management API)."""
    base = f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        description = await _management(client, f"{base}/management/v1/description")
        devices = await _management(client, f"{base}/management/v1/configureddevices")
    info = description if isinstance(description, dict) else {}
    return AlpacaServerInfo(
        host=host,
        port=port,
        name=str(info.get("ServerName") or ""),
        manufacturer=str(info.get("Manufacturer") or ""),
        version=str(info.get("ManufacturerVersion") or ""),
        location=str(info.get("Location") or ""),
        devices=[_device(d) for d in devices or [] if isinstance(d, dict)],
    )


async def _management(client: httpx.AsyncClient, url: str) -> object:
    response = await client.get(url)
    response.raise_for_status()
    body = response.json()
    if int(body.get("ErrorNumber") or 0):
        raise ValueError(str(body.get("ErrorMessage") or "management API error"))
    return body.get("Value")


def _device(d: dict) -> AlpacaDeviceInfo:
    device_type = str(d.get("DeviceType") or "")
    kind, adapter = DEVICE_KINDS.get(device_type.lower(), (None, None))
    return AlpacaDeviceInfo(
        name=str(d.get("DeviceName") or device_type),
        device_type=device_type,
        device_number=int(d.get("DeviceNumber") or 0),
        unique_id=str(d.get("UniqueID") or ""),
        kind=kind,
        adapter_key=adapter,
    )


def parse_address(address: str) -> tuple[str, int]:
    """'host', 'host:port' or '[v6]:port' → (host, port); ValueError if it is neither."""
    text = address.strip()
    if not text:
        raise ValueError("empty address")
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = rest.removeprefix(":") or str(DEFAULT_ALPACA_PORT)
    elif text.count(":") == 1:
        host, port = text.split(":")
    else:
        host, port = text, str(DEFAULT_ALPACA_PORT)
    if not _valid_host(host) or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError(f"not an address: {address!r}")
    return host, int(port)


_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*$")


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return ":" not in host and bool(_HOSTNAME.match(host))


async def find_servers(
    extra: list[str] | None = None,
    *,
    timeout: float = 1.5,
    discovery_addresses: list[str] | None = None,
    discovery_port: int | None = None,
) -> tuple[list[AlpacaServerInfo], list[AddressError]]:
    """Every server discovery finds, plus those at *extra* addresses, with their devices.

    A server found more than once (on 127.0.0.1 and on its network address) is listed once,
    by its loopback address when it is this machine.
    """
    errors: list[AddressError] = []
    targets: dict[tuple[str, int], str] = {}
    for address in extra or []:
        try:
            targets[parse_address(address)] = address
        except ValueError as exc:
            errors.append(AddressError(address=address, error=str(exc)))
    for found in await discover_servers(timeout, addresses=discovery_addresses, port=discovery_port):
        targets.setdefault(found, f"{found[0]}:{found[1]}")

    results = await asyncio.gather(*(describe_server(h, p) for h, p in targets), return_exceptions=True)
    servers: list[AlpacaServerInfo] = []
    for address, result in zip(targets.values(), results):
        if isinstance(result, BaseException):
            errors.append(AddressError(address=address, error=_reason(result)))
        else:
            servers.append(result)
    return _dedupe(servers), errors


def _reason(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}: not an Alpaca server?"
    if isinstance(exc, httpx.HTTPError):
        return "no answer" if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)) else str(exc)
    return str(exc)


def _dedupe(servers: list[AlpacaServerInfo]) -> list[AlpacaServerInfo]:
    by_identity: dict[tuple, AlpacaServerInfo] = {}
    for server in sorted(servers, key=lambda s: (not s.host.startswith("127."), s.host)):
        ids = tuple(sorted(d.unique_id for d in server.devices if d.unique_id))
        identity = (server.port, ids) if ids else (server.host, server.port)
        by_identity.setdefault(identity, server)
    return sorted(by_identity.values(), key=lambda s: (s.name.lower(), s.host, s.port))
