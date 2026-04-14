"""
Bundled INDI plugin — registers IndiCamera, IndiMount, IndiFocuser.

This module is imported directly by astrolol.app when building the plugin
manager.  It handles the ImportError from pyindi-client gracefully so the
rest of the application still starts when INDI is not installed.

Device classes are registered as thin factory subclasses that capture the
shared IndiConnectionManager, which in turn lazily starts indiserver and
connects the PyIndi client on the first device connection.
"""
from __future__ import annotations

import asyncio
import structlog

import pluggy

from astrolol.plugin import hookimpl
from astrolol.devices.registry import DeviceRegistry

logger = structlog.get_logger()


class IndiConnectionManager:
    """
    Shared indiserver + PyIndi client lifecycle.

    The first INDI device that connects triggers:
      1. IndiServer.start()  (or no-op if unmanaged)
      2. IndiClient.connect()

    Subsequent devices reuse the same client.  Ref-counting keeps the
    connection alive as long as at least one device is connected.
    """

    def __init__(self) -> None:
        from astrolol.config.settings import settings
        from astrolol.devices.indi.server import IndiServer
        from astrolol.devices.indi.client import IndiClient

        self._server = IndiServer(
            manage=settings.indi_manage_server,
            host=settings.indi_host,
            port=settings.indi_port,
        )
        self._client = IndiClient(
            host=settings.indi_host,
            port=settings.indi_port,
        )
        # Lock and loop reference are created lazily in acquire() so they bind
        # to the correct running event loop.  This matters when the same
        # IndiConnectionManager instance is used across multiple event loops
        # (e.g. in tests where each test function gets its own loop).
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ref_count = 0
        self._started = False

    async def acquire(self) -> None:
        """Called by each INDI adapter on connect(). Starts services on first call."""
        current_loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not current_loop:
            # First call, or the event loop changed (e.g. between test functions).
            # Reset so we reconnect in the new loop with fresh asyncio primitives.
            self._lock = asyncio.Lock()
            self._loop = current_loop
            self._started = False
        async with self._lock:
            if not self._started:
                await self._server.start()
                await self._client.connect()
                self._started = True
            self._ref_count += 1

    async def release(self) -> None:
        """Called by each INDI adapter on disconnect()."""
        async with self._lock:
            self._ref_count = max(0, self._ref_count - 1)
            # We intentionally keep the server alive until app shutdown so
            # re-connecting a device is fast.  The server will be reaped by
            # the OS when astrolol exits.

    @property
    def client(self):  # type: ignore[return]
        return self._client

    async def load_driver(self, executable: str) -> None:
        await self._server.load_driver(executable)

    async def unload_driver(self, executable: str) -> None:
        await self._server.unload_driver(executable)


def _make_camera_class(manager: IndiConnectionManager):
    """Return an IndiCamera subclass that uses the shared manager."""
    from astrolol.devices.indi.camera import IndiCamera

    class _Camera(IndiCamera):
        _manager = manager

        def __init__(self, device_name: str, executable: str = "", device_port: str = "", **_kwargs):
            super().__init__(device_name=device_name, client=manager.client, device_port=device_port or None)
            self._executable = executable

        async def connect(self) -> None:
            if self._manager._server.manage and not self._executable:
                raise ValueError(
                    "INDI driver executable is required when astrolol manages indiserver. "
                    "Select a driver from the catalog or enter an executable name "
                    "(e.g. indi_asi_ccd)."
                )
            await self._manager.acquire()
            if self._executable:
                await self._manager.load_driver(self._executable)
            await super().connect()

        async def disconnect(self) -> None:
            try:
                await super().disconnect()
            finally:
                if self._executable:
                    await self._manager.unload_driver(self._executable)
                await self._manager.release()

    _Camera.__name__ = "IndiCamera"
    _Camera.__qualname__ = "IndiCamera"
    return _Camera


def _make_mount_class(manager: IndiConnectionManager):
    from astrolol.devices.indi.mount import IndiMount

    class _Mount(IndiMount):
        _manager = manager

        def __init__(self, device_name: str, executable: str = "", device_port: str = "", **_kwargs):
            super().__init__(device_name=device_name, client=manager.client, device_port=device_port or None)
            self._executable = executable

        async def connect(self) -> None:
            if self._manager._server.manage and not self._executable:
                raise ValueError(
                    "INDI driver executable is required when astrolol manages indiserver. "
                    "Select a driver from the catalog or enter an executable name "
                    "(e.g. indi_eqmod_telescope)."
                )
            await self._manager.acquire()
            if self._executable:
                await self._manager.load_driver(self._executable)
            await super().connect()

        async def disconnect(self) -> None:
            try:
                await super().disconnect()
            finally:
                if self._executable:
                    await self._manager.unload_driver(self._executable)
                await self._manager.release()

    _Mount.__name__ = "IndiMount"
    _Mount.__qualname__ = "IndiMount"
    return _Mount


def _make_focuser_class(manager: IndiConnectionManager):
    from astrolol.devices.indi.focuser import IndiFocuser

    class _Focuser(IndiFocuser):
        _manager = manager

        def __init__(self, device_name: str, executable: str = "", device_port: str = "", **_kwargs):
            super().__init__(device_name=device_name, client=manager.client, device_port=device_port or None)
            self._executable = executable

        async def connect(self) -> None:
            if self._manager._server.manage and not self._executable:
                raise ValueError(
                    "INDI driver executable is required when astrolol manages indiserver. "
                    "Select a driver from the catalog or enter an executable name "
                    "(e.g. indi_focus_focuser)."
                )
            await self._manager.acquire()
            if self._executable:
                await self._manager.load_driver(self._executable)
            await super().connect()

        async def disconnect(self) -> None:
            try:
                await super().disconnect()
            finally:
                if self._executable:
                    await self._manager.unload_driver(self._executable)
                await self._manager.release()

    _Focuser.__name__ = "IndiFocuser"
    _Focuser.__qualname__ = "IndiFocuser"
    return _Focuser


class IndiPlugin:
    """pluggy hookimpl that registers all INDI adapters."""

    @hookimpl
    def register_devices(self, registry: DeviceRegistry) -> None:
        try:
            manager = IndiConnectionManager()
        except RuntimeError as exc:
            logger.warning("indi.plugin_skipped", reason=str(exc))
            return

        registry.register_camera("indi_camera", _make_camera_class(manager))
        registry.register_mount("indi_mount", _make_mount_class(manager))
        registry.register_focuser("indi_focuser", _make_focuser_class(manager))
        registry.indi_client = manager.client
        logger.info("indi.adapters_registered")
