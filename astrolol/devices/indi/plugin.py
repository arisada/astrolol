"""
Bundled INDI plugin — registers IndiCamera, IndiMount, IndiFocuser,
IndiFilterWheel, IndiRotator, IndiRawDevice, and multi-role companion discovery.

This module is imported directly by astrolol.app when building the plugin
manager.  It handles the ImportError from pyindi-client gracefully so the
rest of the application still starts when INDI is not installed.

Device classes are registered as thin factory subclasses that capture the
shared IndiConnectionManager, which in turn lazily starts indiserver and
connects the PyIndi client on the first device connection.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

import pluggy

from astrolol.plugin import hookimpl
from astrolol.devices.config import DeviceConfig
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

    def __init__(self, run_dir: Path = Path("/tmp/astrolol")) -> None:
        from astrolol.config.settings import settings
        from astrolol.devices.indi.server import IndiServer
        from astrolol.devices.indi.client import IndiClient

        self._server = IndiServer(
            manage=settings.indi_manage_server,
            host=settings.indi_host,
            port=settings.indi_port,
            run_dir=run_dir,
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

    async def ensure_started(self) -> None:
        """Ensure indiserver and PyIndi client are running.

        Unlike acquire(), does not increment ref count.  Use this when you need
        INDI services running (e.g. to load a driver and inspect its properties)
        but are not yet connecting a device.
        """
        current_loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not current_loop:
            self._lock = asyncio.Lock()
            self._loop = current_loop
            self._started = False
        async with self._lock:
            if not self._started:
                await self._server.start()
                await self._client.connect()
                self._started = True

    async def release(self) -> None:
        """Called by each INDI adapter on disconnect()."""
        async with self._lock:
            self._ref_count = max(0, self._ref_count - 1)
            # We intentionally keep the server alive until app shutdown so
            # re-connecting a device is fast.  The server will be reaped by
            # the OS when astrolol exits.

    async def discover_roles(self, device_name: str) -> list[str]:
        """Wait for properties to stabilize then return discovered role kinds."""
        # Poll until property count stops growing
        prev_count = -1
        while True:
            await asyncio.sleep(1.0)
            device = self._client.data.get(device_name) or {}
            count = len(device)
            if count == prev_count:
                break
            prev_count = count

        roles = []
        client = self._client
        if client._get_vector(device_name, "CCD_EXPOSURE") is not None or client._get_vector(device_name, "CCD1") is not None:
            roles.append("camera")
        if client._get_vector(device_name, "EQUATORIAL_EOD_COORD") is not None:
            roles.append("mount")
        if client._get_vector(device_name, "ABS_FOCUS_POSITION") is not None:
            roles.append("focuser")
        if client._get_vector(device_name, "FILTER_SLOT") is not None:
            roles.append("filter_wheel")
        if client._get_vector(device_name, "ABS_ROTATOR_ANGLE") is not None:
            roles.append("rotator")
        return roles

    @property
    def client(self):  # type: ignore[return]
        return self._client

    async def load_driver(self, executable: str) -> None:
        await self._server.load_driver(executable)

    async def unload_driver(self, executable: str) -> None:
        await self._server.unload_driver(executable)

    async def stop_server(self) -> None:
        """Explicitly stop indiserver (called from the admin endpoint)."""
        if self._lock is None:
            await self._server.stop()
            return
        async with self._lock:
            await self._server.stop()
            self._started = False
            self._ref_count = 0


def _make_camera_class(manager: IndiConnectionManager):
    """Return an IndiCamera subclass that uses the shared manager."""
    from astrolol.devices.indi.camera import IndiCamera

    class _Camera(IndiCamera):
        _manager = manager

        def __init__(self, device_name: str, executable: str = "",
                     pre_connect_props: dict | None = None,
                     device_port: str = "", device_baud_rate: str = "", **_kwargs):
            props = dict(pre_connect_props or {})
            if device_port and "DEVICE_PORT" not in props:
                props["DEVICE_PORT"] = {"values": {"PORT": device_port}}
            if device_baud_rate and "DEVICE_BAUD_RATE" not in props:
                props["DEVICE_BAUD_RATE"] = {"on_elements": [device_baud_rate]}
            super().__init__(device_name=device_name, client=manager.client,
                             pre_connect_props=props or None)
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

        def __init__(self, device_name: str, executable: str = "",
                     pre_connect_props: dict | None = None,
                     device_port: str = "", device_baud_rate: str = "", **_kwargs):
            props = dict(pre_connect_props or {})
            if device_port and "DEVICE_PORT" not in props:
                props["DEVICE_PORT"] = {"values": {"PORT": device_port}}
            if device_baud_rate and "DEVICE_BAUD_RATE" not in props:
                props["DEVICE_BAUD_RATE"] = {"on_elements": [device_baud_rate]}
            super().__init__(device_name=device_name, client=manager.client,
                             pre_connect_props=props or None)
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

        def __init__(self, device_name: str, executable: str = "",
                     pre_connect_props: dict | None = None,
                     device_port: str = "", device_baud_rate: str = "", **_kwargs):
            props = dict(pre_connect_props or {})
            if device_port and "DEVICE_PORT" not in props:
                props["DEVICE_PORT"] = {"values": {"PORT": device_port}}
            if device_baud_rate and "DEVICE_BAUD_RATE" not in props:
                props["DEVICE_BAUD_RATE"] = {"on_elements": [device_baud_rate]}
            super().__init__(device_name=device_name, client=manager.client,
                             pre_connect_props=props or None)
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


def _make_filter_wheel_class(manager: IndiConnectionManager):
    from astrolol.devices.indi.filter_wheel import IndiFilterWheel

    class _FilterWheel(IndiFilterWheel):
        _manager = manager

        def __init__(self, device_name: str, executable: str = "",
                     pre_connect_props: dict | None = None,
                     device_port: str = "", device_baud_rate: str = "", **_kwargs):
            props = dict(pre_connect_props or {})
            if device_port and "DEVICE_PORT" not in props:
                props["DEVICE_PORT"] = {"values": {"PORT": device_port}}
            if device_baud_rate and "DEVICE_BAUD_RATE" not in props:
                props["DEVICE_BAUD_RATE"] = {"on_elements": [device_baud_rate]}
            super().__init__(device_name=device_name, client=manager.client,
                             pre_connect_props=props or None)
            self._executable = executable

        async def connect(self) -> None:
            if self._manager._server.manage and not self._executable:
                raise ValueError(
                    "INDI driver executable is required when astrolol manages indiserver. "
                    "Select a driver from the catalog or enter an executable name "
                    "(e.g. indi_efw)."
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

    _FilterWheel.__name__ = "IndiFilterWheel"
    _FilterWheel.__qualname__ = "IndiFilterWheel"
    return _FilterWheel


def _make_rotator_class(manager: IndiConnectionManager):
    from astrolol.devices.indi.rotator import IndiRotator

    class _Rotator(IndiRotator):
        _manager = manager

        def __init__(self, device_name: str, executable: str = "",
                     pre_connect_props: dict | None = None, **_kwargs):
            super().__init__(device_name=device_name, client=manager.client,
                             pre_connect_props=pre_connect_props or None)
            self._executable = executable

        async def connect(self) -> None:
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

    _Rotator.__name__ = "IndiRotator"
    _Rotator.__qualname__ = "IndiRotator"
    return _Rotator


def _make_indi_raw_class(manager: IndiConnectionManager):
    from astrolol.devices.indi.raw import IndiRawDevice

    class _IndiRaw(IndiRawDevice):
        _manager = manager

        def __init__(self, device_name: str, executable: str = "", **_kwargs):
            super().__init__(device_name=device_name, client=manager.client)
            self._executable = executable

        async def connect(self) -> None:
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

    _IndiRaw.__name__ = "IndiRawDevice"
    _IndiRaw.__qualname__ = "IndiRawDevice"
    return _IndiRaw


class IndiPlugin:
    """pluggy hookimpl that registers all INDI adapters."""

    @hookimpl
    def register_devices(self, registry: DeviceRegistry) -> None:
        try:
            run_dir = getattr(registry, "indi_run_dir", Path("/tmp/astrolol"))
            manager = IndiConnectionManager(run_dir=run_dir)
        except RuntimeError as exc:
            logger.warning("indi.plugin_skipped", reason=str(exc))
            return

        registry.register_camera("indi_camera", _make_camera_class(manager))
        registry.register_mount("indi_mount", _make_mount_class(manager))
        registry.register_focuser("indi_focuser", _make_focuser_class(manager))
        registry.register_filter_wheel("indi_filter_wheel", _make_filter_wheel_class(manager))
        registry.register_rotator("indi_rotator", _make_rotator_class(manager))
        registry.register_indi_raw("indi_raw", _make_indi_raw_class(manager))
        registry.indi_client = manager.client
        registry.indi_manager = manager

        # Set up companion discoverer for multi-role INDI drivers
        async def companion_discoverer(config: DeviceConfig) -> list[DeviceConfig]:
            device_name = config.params.get("device_name", "")
            if not device_name:
                return []

            roles = await manager.discover_roles(device_name)
            primary_kind = config.kind

            # Build a set of already-connected device kinds for this driver
            # (We can't easily check the device_manager here, so we just exclude primary)
            companion_configs = []
            for role in roles:
                if role == primary_kind:
                    continue
                adapter_key = f"indi_{role}"
                companion_config = DeviceConfig(
                    kind=role,
                    adapter_key=adapter_key,
                    params={"device_name": device_name, "executable": ""},
                    driver_name=device_name,
                )
                companion_configs.append(companion_config)

            return companion_configs

        registry.companion_discoverer = companion_discoverer
        logger.info("indi.adapters_registered")
