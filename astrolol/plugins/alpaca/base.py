"""What every Alpaca adapter shares: the device it talks to, connecting, and waiting on it."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from astrolol.plugins.alpaca.client import AlpacaClient, AlpacaError
from astrolol.devices.base.models import DeviceState

logger = structlog.get_logger()

DEFAULT_PORT = 11111   # Alpaca's usual port; OmniSim's is 32323


class AlpacaDevice:
    """One Alpaca device, addressed by host, port and device number.

    The connect params of every Alpaca adapter: ``host``, ``port``, ``device_number``.
    """

    DEVICE_TYPE = ""   # "camera", "telescope", …
    DEFAULT_CONNECT_PARAMS: dict[str, Any] = {"host": "127.0.0.1", "port": DEFAULT_PORT, "device_number": 0}

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        device_number: int = 0,
        *,
        client: AlpacaClient | None = None,
        **_kwargs: Any,
    ) -> None:
        self._alpaca = client or AlpacaClient(host, int(port), self.DEVICE_TYPE, int(device_number))
        self._state = DeviceState.DISCONNECTED
        self.name: str | None = None

    async def connect(self) -> None:
        self._state = DeviceState.CONNECTING
        try:
            await self._alpaca.put("connected", Connected=True)
            if not await self._alpaca.get("connected"):
                raise AlpacaError(f"{self._alpaca.device_type} {self._alpaca.device_number} did not connect")
            self.name = await self._alpaca.get_or("name", None)
            await self._on_connected()
        except Exception:
            self._state = DeviceState.ERROR
            await self._alpaca.close()
            raise
        self._state = DeviceState.CONNECTED
        logger.info("alpaca.device_connected", device=repr(self._alpaca), name=self.name)

    async def _on_connected(self) -> None:
        """Read what the device can do, once connected."""

    async def disconnect(self) -> None:
        try:
            await self._on_disconnecting()
            await self._alpaca.put("connected", Connected=False)
        except AlpacaError as exc:
            logger.warning("alpaca.disconnect_failed", device=repr(self._alpaca), error=str(exc))
        finally:
            self._state = DeviceState.DISCONNECTED
            await self._alpaca.close()

    async def _on_disconnecting(self) -> None:
        """Stop what the adapter runs in the background."""

    async def ping(self) -> bool:
        try:
            return bool(await self._alpaca.get("connected"))
        except AlpacaError:
            return False

    async def _wait_until(
        self,
        done: Callable[[], Awaitable[bool]],
        timeout: float,
        what: str,
        interval: float = 0.25,
    ) -> None:
        """Poll *done* until it is true; TimeoutError after *timeout* seconds."""
        deadline = time.monotonic() + timeout
        while not await done():
            if time.monotonic() > deadline:
                raise TimeoutError(f"{self._alpaca.device_type} {self._alpaca.device_number}: {what} "
                                   f"not done after {timeout:g} s")
            await asyncio.sleep(interval)
