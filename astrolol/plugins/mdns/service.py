"""mDNS service advertisement — lets the Android app (or anything else) find astrolol
on the local network via `_astrolol._tcp.local.` instead of a typed-in IP.

Advertises this machine as `<hostname>.local`, with the port and scheme from
astrolol.plugins.mdns.models.MdnsSettings (the port defaults to the one astrolol binds).
"""

from __future__ import annotations

import socket

import ifaddr
import structlog
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from astrolol.version import PROTOCOL_VERSION, SERVER_VERSION
from astrolol.plugins.mdns.models import DEFAULT_PORT, MdnsSettings

logger = structlog.get_logger()

SERVICE_TYPE = "_astrolol._tcp.local."


# Interfaces whose addresses mean nothing to another machine on the network: containers,
# virtual machines, tunnels. Link-local addresses are kept — they make astrolol reachable
# without DHCP. Matched on the interface name.
_VIRTUAL_INTERFACE_PREFIXES = (
    "lo", "docker", "br-", "veth", "virbr", "vboxnet", "vmnet", "lxc", "lxd",
    "tun", "tap", "wg", "tailscale",
)


def _hostname() -> str:
    """This machine's name without its domain (gethostname() may return "pi.lan")."""
    return socket.gethostname().split(".")[0]


def _local_addresses() -> list[str]:
    """Non-loopback IPv4 addresses of the physical interfaces (all of them when every
    interface looks virtual, rather than advertising nothing)."""
    candidates = [
        (adapter.name, ip.ip)
        for adapter in ifaddr.get_adapters()
        for ip in adapter.ips
        if ip.is_IPv4 and isinstance(ip.ip, str) and not ip.ip.startswith("127.")
    ]
    physical = [ip for name, ip in candidates if not name.startswith(_VIRTUAL_INTERFACE_PREFIXES)]
    addresses = physical or [ip for _, ip in candidates]
    return addresses or ["127.0.0.1"]


def build_service_info(settings: MdnsSettings) -> ServiceInfo:
    """The ServiceInfo to advertise: this machine, as <hostname>.local."""
    hostname = _hostname()
    return ServiceInfo(
        SERVICE_TYPE,
        name=f"{settings.instance_name or hostname}.{SERVICE_TYPE}",
        port=settings.advertised_port or DEFAULT_PORT,
        parsed_addresses=_local_addresses(),
        server=f"{hostname}.local.",
        properties={
            "protocol_version": str(PROTOCOL_VERSION),
            "server_version": SERVER_VERSION,
            "scheme": settings.scheme,
        },
    )


class MdnsAdvertiser:
    """Registers one ServiceInfo on startup, unregisters it on shutdown. Idempotent."""

    def __init__(self) -> None:
        self._aiozc: AsyncZeroconf | None = None
        self._info: ServiceInfo | None = None

    async def start(self, settings: MdnsSettings) -> None:
        info = build_service_info(settings)
        self._aiozc = AsyncZeroconf()
        self._info = info
        await self._aiozc.async_register_service(info)
        logger.info(
            "mdns.advertising",
            name=info.name,
            port=info.port,
            server=info.server,
            addresses=info.parsed_addresses(),
        )

    async def stop(self) -> None:
        if self._aiozc is None:
            return
        if self._info is not None:
            await self._aiozc.async_unregister_service(self._info)
        await self._aiozc.async_close()
        self._aiozc = None
        self._info = None
        logger.info("mdns.stopped_advertising")
