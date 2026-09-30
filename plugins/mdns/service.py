"""mDNS service advertisement — lets the Android app (or anything else) find astrolol
on the local network via `_astrolol._tcp.local.` instead of a typed-in IP.

Advertises whatever plugins.mdns.models.MdnsSettings says to advertise. astrolol has no
way to know the network-visible host/port/scheme itself (see models.py), so an unset
port means there's nothing sensible to advertise and the plugin stays quiet rather than
guessing.
"""

from __future__ import annotations

import ipaddress
import socket

import ifaddr
import structlog
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from astrolol.version import PROTOCOL_VERSION, SERVER_VERSION
from plugins.mdns.models import MdnsSettings

logger = structlog.get_logger()

SERVICE_TYPE = "_astrolol._tcp.local."


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _local_addresses() -> list[str]:
    """All non-loopback IPv4 addresses bound to a local interface."""
    addresses = [
        ip.ip
        for adapter in ifaddr.get_adapters()
        for ip in adapter.ips
        if ip.is_IPv4 and isinstance(ip.ip, str) and ip.ip != "127.0.0.1"
    ]
    return addresses or ["127.0.0.1"]


def build_service_info(settings: MdnsSettings) -> ServiceInfo | None:
    """Return the ServiceInfo to advertise, or None if there's nothing sensible to say."""
    if not settings.advertised_port:
        return None

    instance_name = settings.instance_name or socket.gethostname()
    host = settings.advertised_host

    if host and _is_ip(host):
        addresses = [host]
        server = f"{socket.gethostname()}.local."
    elif host:
        addresses = _local_addresses()
        server = host if host.endswith(".") else f"{host}."
    else:
        addresses = _local_addresses()
        server = f"{socket.gethostname()}.local."

    return ServiceInfo(
        SERVICE_TYPE,
        name=f"{instance_name}.{SERVICE_TYPE}",
        port=settings.advertised_port,
        parsed_addresses=addresses,
        server=server,
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
        if info is None:
            logger.info("mdns.not_advertising", reason="advertised_port is not set")
            return
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
