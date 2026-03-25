"""
Async wrapper around the synchronous pyindi-client C extension.

All blocking calls are dispatched via asyncio.to_thread() so a stuck or
slow INDI device cannot block the event loop.

If pyindi-client is not installed this module can still be imported; the
``IndiClient`` class will raise ``RuntimeError`` on instantiation.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import structlog

logger = structlog.get_logger()

try:
    import PyIndi  # type: ignore[import]
    _PYINDI_AVAILABLE = True
    _BaseIndiClient: type = PyIndi.BaseClient
except ImportError:
    _PYINDI_AVAILABLE = False
    PyIndi = None  # type: ignore[assignment]
    _BaseIndiClient = object


# ---------------------------------------------------------------------------
# Low-level synchronous INDI client (runs in a dedicated thread)
# ---------------------------------------------------------------------------

class _SyncIndiClient(_BaseIndiClient):  # type: ignore[misc,valid-type]
    """
    Thin subclass of PyIndi.BaseClient that receives property updates and
    stores them in thread-safe dicts.

    All methods are synchronous and must only be called from the worker thread.
    """

    def __init__(self) -> None:
        if not _PYINDI_AVAILABLE:
            raise RuntimeError(
                "pyindi-client is not installed.  "
                "Install it with: pip install pyindi-client"
            )
        super().__init__()
        self._lock = threading.Lock()
        # device_name → property_name → IProperty
        self._properties: dict[str, dict[str, Any]] = {}
        # device_name → BLOB
        self._blobs: dict[str, Any] = {}
        # Condition var signalled whenever a property changes
        self._updated = threading.Condition(self._lock)

    # ---- PyIndi callbacks -------------------------------------------------

    def newDevice(self, d: Any) -> None:  # noqa: N802
        with self._lock:
            self._properties.setdefault(d.getDeviceName(), {})

    def removeDevice(self, d: Any) -> None:  # noqa: N802
        with self._lock:
            self._properties.pop(d.getDeviceName(), None)

    def newProperty(self, p: Any) -> None:  # noqa: N802
        with self._updated:
            self._properties.setdefault(p.getDeviceName(), {})[p.getName()] = p
            self._updated.notify_all()

    def removeProperty(self, p: Any) -> None:  # noqa: N802
        with self._lock:
            dev = self._properties.get(p.getDeviceName(), {})
            dev.pop(p.getName(), None)

    def updateProperty(self, p: Any) -> None:  # noqa: N802
        with self._updated:
            self._properties.setdefault(p.getDeviceName(), {})[p.getName()] = p
            self._updated.notify_all()

    def newBLOB(self, bp: Any) -> None:  # noqa: N802
        with self._updated:
            self._blobs[bp.bvp.device] = bp
            self._updated.notify_all()

    # PyIndi ≥ 1.9 uses newMessage / serverConnected / serverDisconnected
    def newMessage(self, d: Any, m: int) -> None: ...  # noqa: N802
    def serverConnected(self) -> None: ...  # noqa: N802
    def serverDisconnected(self, code: int) -> None: ...  # noqa: N802

    # ---- Synchronous helpers ----------------------------------------------

    def wait_for_property(
        self, device_name: str, prop_name: str, timeout: float = 10.0
    ) -> Any:
        deadline = time.monotonic() + timeout
        with self._updated:
            while True:
                prop = self._properties.get(device_name, {}).get(prop_name)
                if prop is not None:
                    return prop
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"INDI property {device_name}/{prop_name} not available "
                        f"after {timeout}s"
                    )
                self._updated.wait(timeout=min(remaining, 0.5))

    def wait_for_blob(self, device_name: str, timeout: float = 60.0) -> Any:
        deadline = time.monotonic() + timeout
        with self._updated:
            while True:
                blob = self._blobs.pop(device_name, None)
                if blob is not None:
                    return blob
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"INDI BLOB for {device_name} not received after {timeout}s"
                    )
                self._updated.wait(timeout=min(remaining, 0.5))

    def get_number(self, device_name: str, prop_name: str, element: str) -> float:
        prop = self._properties.get(device_name, {}).get(prop_name)
        if prop is None:
            raise KeyError(f"Property {device_name}/{prop_name} not found")
        for i in range(prop.count):
            el = prop[i]
            if el.name == element:
                return float(el.value)
        raise KeyError(f"Element {element} not found in {device_name}/{prop_name}")

    def get_switch_state(self, device_name: str, prop_name: str, element: str) -> bool:
        prop = self._properties.get(device_name, {}).get(prop_name)
        if prop is None:
            raise KeyError(f"Property {device_name}/{prop_name} not found")
        for i in range(prop.count):
            el = prop[i]
            if el.name == element:
                return el.s == PyIndi.ISS_ON
        raise KeyError(f"Element {element} not found in {device_name}/{prop_name}")

    def set_number(
        self, device_name: str, prop_name: str, values: dict[str, float]
    ) -> None:
        prop = self.wait_for_property(device_name, prop_name)
        for i in range(prop.count):
            el = prop[i]
            if el.name in values:
                el.value = values[el.name]
        self.sendNewNumber(prop)  # type: ignore[attr-defined]

    def set_switch(
        self, device_name: str, prop_name: str, on_elements: list[str]
    ) -> None:
        prop = self.wait_for_property(device_name, prop_name)
        for i in range(prop.count):
            el = prop[i]
            el.s = PyIndi.ISS_ON if el.name in on_elements else PyIndi.ISS_OFF
        self.sendNewSwitch(prop)  # type: ignore[attr-defined]

    def enable_blob(self, device_name: str) -> None:
        self.setBLOBMode(PyIndi.B_FULL, device_name, None)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Public async wrapper
# ---------------------------------------------------------------------------

class IndiClient:
    """
    Async façade over _SyncIndiClient.

    Each blocking operation runs in asyncio.to_thread() so a stuck device
    only blocks that thread, not the event loop.
    """

    def __init__(self, host: str = "localhost", port: int = 7624) -> None:
        if not _PYINDI_AVAILABLE:
            raise RuntimeError(
                "pyindi-client is not installed.  "
                "Install it with: pip install pyindi-client"
            )
        self.host = host
        self.port = port
        self._sync = _SyncIndiClient()

    async def connect(self) -> None:
        def _connect() -> None:
            self._sync.setServer(self.host, self.port)  # type: ignore[attr-defined]
            if not self._sync.connectServer():  # type: ignore[attr-defined]
                raise ConnectionError(
                    f"Could not connect to indiserver at {self.host}:{self.port}"
                )
        await asyncio.to_thread(_connect)
        logger.info("indi.client_connected", host=self.host, port=self.port)

    async def disconnect(self) -> None:
        await asyncio.to_thread(self._sync.disconnectServer)  # type: ignore[attr-defined]

    async def wait_for_property(
        self, device_name: str, prop_name: str, timeout: float = 10.0
    ) -> Any:
        return await asyncio.to_thread(
            self._sync.wait_for_property, device_name, prop_name, timeout
        )

    async def wait_for_blob(self, device_name: str, timeout: float = 60.0) -> Any:
        return await asyncio.to_thread(self._sync.wait_for_blob, device_name, timeout)

    async def get_number(
        self, device_name: str, prop_name: str, element: str
    ) -> float:
        return await asyncio.to_thread(
            self._sync.get_number, device_name, prop_name, element
        )

    async def get_switch_state(
        self, device_name: str, prop_name: str, element: str
    ) -> bool:
        return await asyncio.to_thread(
            self._sync.get_switch_state, device_name, prop_name, element
        )

    async def set_number(
        self, device_name: str, prop_name: str, values: dict[str, float]
    ) -> None:
        await asyncio.to_thread(self._sync.set_number, device_name, prop_name, values)

    async def set_switch(
        self, device_name: str, prop_name: str, on_elements: list[str]
    ) -> None:
        await asyncio.to_thread(
            self._sync.set_switch, device_name, prop_name, on_elements
        )

    async def enable_blob(self, device_name: str) -> None:
        await asyncio.to_thread(self._sync.enable_blob, device_name)

    async def connect_device(self, device_name: str, timeout: float = 10.0) -> None:
        """Send CONNECTION=ON to the INDI device and wait for it to be ready."""
        await self.set_switch(device_name, "CONNECTION", ["CONNECT"])
        # Wait for the connection switch to confirm
        await asyncio.to_thread(
            self._sync.wait_for_property, device_name, "CONNECTION", timeout
        )
        logger.info("indi.device_connected", device=device_name)

    async def disconnect_device(self, device_name: str) -> None:
        await self.set_switch(device_name, "CONNECTION", ["DISCONNECT"])
        logger.info("indi.device_disconnected", device=device_name)
