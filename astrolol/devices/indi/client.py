"""
Async wrapper around the synchronous pyindi-client C extension (PyIndi 2.x).

All blocking calls are dispatched via asyncio.to_thread() so a stuck or
slow INDI device cannot block the event loop.

PyIndi 2.x API notes:
  - newProperty(p) / updateProperty(p) receive a generic Property object.
  - p.getNumber() → PropertyViewNumber, p.getSwitch() → PropertyViewSwitch,
    p.getBLOB()   → PropertyViewBlob  (each with count(), findWidgetByName())
  - WidgetViewNumber: .getValue(), .setValue(), .getName()
  - WidgetViewSwitch: .s (ISS_ON/ISS_OFF), .getName()
  - WidgetViewBlob:   .getblobdata(), .getBlobLen(), .getFormat()
  - IPS_IDLE=0, IPS_OK=1, IPS_BUSY=2, IPS_ALERT=3
  - BLOBs arrive via updateProperty (no separate newBLOB in 2.x).
  - setBLOBMode uses B_ALSO (enables BLOBs while keeping regular property updates).
  - BaseClient.connectDevice(name) / disconnectDevice(name) are built-in.
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
    """

    def __init__(self) -> None:
        if not _PYINDI_AVAILABLE:
            raise RuntimeError(
                "pyindi-client is not installed.  "
                "Install it with: pip install pyindi-client"
            )
        super().__init__()
        self._lock = threading.Lock()
        # device_name → property_name → Property
        self._properties: dict[str, dict[str, Any]] = {}
        # Condition var signalled whenever any property changes
        self._updated = threading.Condition(self._lock)
        # Set to True during/after disconnect so C callbacks become no-ops
        self._active = True
        # Monotonically increasing counter per BLOB property so wait_for_blob
        # can detect a new delivery even when the payload size is identical.
        self._blob_versions: dict[tuple[str, str], int] = {}

    # ---- PyIndi 2.x callbacks -------------------------------------------

    def newDevice(self, d: Any) -> None:  # noqa: N802
        if not self._active:
            return
        with self._lock:
            self._properties.setdefault(d.getDeviceName(), {})

    def removeDevice(self, d: Any) -> None:  # noqa: N802
        if not self._active:
            return
        with self._lock:
            self._properties.pop(d.getDeviceName(), None)

    def newProperty(self, p: Any) -> None:  # noqa: N802
        if not self._active:
            return
        with self._updated:
            self._properties.setdefault(p.getDeviceName(), {})[p.getName()] = p
            self._updated.notify_all()

    def removeProperty(self, p: Any) -> None:  # noqa: N802
        if not self._active:
            return
        with self._lock:
            self._properties.get(p.getDeviceName(), {}).pop(p.getName(), None)

    def updateProperty(self, p: Any) -> None:  # noqa: N802
        if not self._active:
            return
        with self._updated:
            dev, name = p.getDeviceName(), p.getName()
            self._properties.setdefault(dev, {})[name] = p
            if p.getType() == PyIndi.INDI_BLOB:
                key = (dev, name)
                self._blob_versions[key] = self._blob_versions.get(key, 0) + 1
            self._updated.notify_all()

    # PyIndi 2.x still has these as overridable hooks
    def newMessage(self, d: Any, m: int) -> None: ...  # noqa: N802
    def serverConnected(self) -> None: ...  # noqa: N802
    def serverDisconnected(self, code: int) -> None: ...  # noqa: N802

    # ---- Synchronous helpers --------------------------------------------

    def wait_for_property(
        self, device_name: str, prop_name: str, timeout: float = 10.0
    ) -> Any:
        """Block until Property(device_name, prop_name) exists and is non-empty."""
        deadline = time.monotonic() + timeout
        with self._updated:
            while True:
                p = self._properties.get(device_name, {}).get(prop_name)
                if p is not None and not p.isEmpty():
                    return p
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"INDI property {device_name}/{prop_name} not available "
                        f"after {timeout}s"
                    )
                self._updated.wait(timeout=min(remaining, 0.5))

    def wait_for_blob(
        self, device_name: str, prop_name: str, timeout: float = 60.0
    ) -> Any:
        """
        Block until a BLOB property update with non-zero data arrives for
        (device_name, prop_name).  Returns the first WidgetViewBlob.

        Uses a version counter (incremented by updateProperty on each BLOB
        delivery) so that consecutive exposures of the same size are detected
        correctly — the old length-comparison heuristic failed for simulators
        that always produce identically-sized frames.
        """
        deadline = time.monotonic() + timeout
        key = (device_name, prop_name)

        # Snapshot the version counter before the exposure was triggered
        with self._lock:
            seen_version = self._blob_versions.get(key, 0)

        with self._updated:
            while True:
                if self._blob_versions.get(key, 0) > seen_version:
                    p = self._properties.get(device_name, {}).get(prop_name)
                    if p is not None and p.getType() == PyIndi.INDI_BLOB:
                        pb = p.getBLOB()
                        if pb.count() > 0 and pb[0].getBlobLen() > 0:
                            return pb[0]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"INDI BLOB {device_name}/{prop_name} not received after {timeout}s"
                    )
                self._updated.wait(timeout=min(remaining, 0.5))

    def get_number(self, device_name: str, prop_name: str, element: str) -> float:
        # Wait briefly in case the property hasn't populated yet
        p = self.wait_for_property(device_name, prop_name, timeout=5.0)
        pn = p.getNumber()
        w = pn.findWidgetByName(element)
        if w is None:
            raise KeyError(f"Element {element} not found in {device_name}/{prop_name}")
        return float(w.getValue())

    def get_switch_state(
        self, device_name: str, prop_name: str, element: str
    ) -> bool:
        p = self.wait_for_property(device_name, prop_name, timeout=5.0)
        ps = p.getSwitch()
        w = ps.findWidgetByName(element)
        if w is None:
            raise KeyError(f"Element {element} not found in {device_name}/{prop_name}")
        return bool(w.s == PyIndi.ISS_ON)

    def get_property_state(self, device_name: str, prop_name: str) -> int:
        """Return the IPS_* state of a property (IPS_IDLE=0, IPS_OK=1, IPS_BUSY=2, IPS_ALERT=3)."""
        p = self._properties.get(device_name, {}).get(prop_name)
        if p is None:
            raise KeyError(f"Property {device_name}/{prop_name} not found")
        return int(p.getState())

    def set_number(
        self, device_name: str, prop_name: str, values: dict[str, float]
    ) -> None:
        p = self.wait_for_property(device_name, prop_name)
        pn = p.getNumber()
        for name, val in values.items():
            w = pn.findWidgetByName(name)
            if w is not None:
                w.setValue(val)
        self.sendNewNumber(pn)  # type: ignore[attr-defined]

    def set_switch(
        self, device_name: str, prop_name: str, on_elements: list[str]
    ) -> None:
        p = self.wait_for_property(device_name, prop_name)
        ps = p.getSwitch()
        for i in range(ps.count()):
            w = ps[i]
            w.s = PyIndi.ISS_ON if w.getName() in on_elements else PyIndi.ISS_OFF
        self.sendNewSwitch(ps)  # type: ignore[attr-defined]

    def get_properties_snapshot(self, device_name: str) -> dict[str, Any]:
        """Return a shallow copy of all cached properties for device_name."""
        with self._lock:
            return dict(self._properties.get(device_name, {}))

    def set_text(
        self, device_name: str, prop_name: str, values: dict[str, str]
    ) -> None:
        p = self.wait_for_property(device_name, prop_name)
        pt = p.getText()
        for name, val in values.items():
            w = pt.findWidgetByName(name)
            if w is not None:
                w.setText(val)
        self.sendNewText(pt)  # type: ignore[attr-defined]

    def enable_blob(self, device_name: str) -> None:
        # B_ALSO = receive BLOBs in addition to regular property updates.
        # B_ONLY would suppress all non-BLOB properties for this device.
        self.setBLOBMode(PyIndi.B_ALSO, device_name, None)  # type: ignore[attr-defined]

    def wait_prop_not_busy(
        self, device_name: str, prop_name: str, timeout: float = 120.0
    ) -> None:
        """Block until property state leaves IPS_BUSY (2)."""
        deadline = time.monotonic() + timeout
        with self._updated:
            while True:
                p = self._properties.get(device_name, {}).get(prop_name)
                if p is not None and p.getState() != PyIndi.IPS_BUSY:
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"{device_name}/{prop_name} still BUSY after {timeout}s"
                    )
                self._updated.wait(timeout=min(remaining, 0.5))

    def wait_for_connection_on(
        self, device_name: str, timeout: float = 10.0
    ) -> None:
        """Block until CONNECTION/CONNECT switch is ISS_ON (device fully connected)."""
        deadline = time.monotonic() + timeout
        with self._updated:
            while True:
                p = self._properties.get(device_name, {}).get("CONNECTION")
                if p is not None:
                    ps = p.getSwitch()
                    w = ps.findWidgetByName("CONNECT")
                    if w is not None and w.s == PyIndi.ISS_ON:
                        return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Device {device_name} did not reach CONNECTION=ON "
                        f"within {timeout}s"
                    )
                self._updated.wait(timeout=min(remaining, 0.5))


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
        # setServer + connectServer must be called from the same thread
        # (not via asyncio.to_thread) because PyIndi internally starts a
        # receiver thread that inherits the calling thread's context.
        self._sync.setServer(self.host, self.port)  # type: ignore[attr-defined]
        ok = await asyncio.to_thread(self._sync.connectServer)  # type: ignore[attr-defined]
        if not ok:
            raise ConnectionError(
                f"Could not connect to indiserver at {self.host}:{self.port}"
            )
        logger.info("indi.client_connected", host=self.host, port=self.port)

    async def disconnect(self) -> None:
        # Mark as inactive first so any in-flight C callbacks become no-ops.
        # We intentionally do NOT call disconnectServer() here: in PyIndi 2.x
        # the C++ receiver thread can segfault when torn down while callbacks
        # are still in flight.  Killing the indiserver process (or the OS at
        # process exit) causes a clean TCP EOF that naturally terminates the
        # receiver thread.
        self._sync._active = False
        await asyncio.sleep(0.05)  # brief drain for any in-flight callbacks

    async def wait_for_property(
        self, device_name: str, prop_name: str, timeout: float = 10.0
    ) -> Any:
        return await asyncio.to_thread(
            self._sync.wait_for_property, device_name, prop_name, timeout
        )

    async def wait_for_blob(
        self, device_name: str, prop_name: str, timeout: float = 60.0
    ) -> Any:
        return await asyncio.to_thread(
            self._sync.wait_for_blob, device_name, prop_name, timeout
        )

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

    async def get_properties_snapshot(self, device_name: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.get_properties_snapshot, device_name)

    async def set_text(
        self, device_name: str, prop_name: str, values: dict[str, str]
    ) -> None:
        await asyncio.to_thread(self._sync.set_text, device_name, prop_name, values)

    async def enable_blob(self, device_name: str) -> None:
        await asyncio.to_thread(self._sync.enable_blob, device_name)

    async def wait_prop_not_busy(
        self, device_name: str, prop_name: str, timeout: float = 120.0
    ) -> None:
        await asyncio.to_thread(
            self._sync.wait_prop_not_busy, device_name, prop_name, timeout
        )

    async def connect_device(self, device_name: str, timeout: float = 10.0) -> None:
        """Connect an INDI device and wait for its full property set to appear.

        Sequence
        --------
        1. Wait for the INDI bus to announce the device + CONNECTION property.
           (Calling connectDevice before this gives "Unable to find driver".)
        2. Send CONNECTION=CONNECT via BaseClient.connectDevice.
        3. Wait until CONNECTION/CONNECT becomes ISS_ON — at this point the
           driver has finished its internal connect and sent all its properties.
        """
        # Step 1 — device must be known before we can connect it
        await self.wait_for_property(device_name, "CONNECTION", timeout=timeout)
        # Step 2 — send the CONNECT command
        await asyncio.to_thread(self._sync.connectDevice, device_name)  # type: ignore[attr-defined]
        # Step 3 — wait for the driver to finish and emit its full property set
        await asyncio.to_thread(
            self._sync.wait_for_connection_on, device_name, timeout
        )
        logger.info("indi.device_connected", device=device_name)

    async def disconnect_device(self, device_name: str) -> None:
        await asyncio.to_thread(self._sync.disconnectDevice, device_name)  # type: ignore[attr-defined]
        logger.info("indi.device_disconnected", device=device_name)
