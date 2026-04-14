"""
Async INDI client built on indipyclient (pure Python, asyncio-native).

indipyclient API notes:
  - IPyClient is a UserDict of devicename → device object.
  - device is a UserDict of vectorname → vector object.
  - vector.state       → 'Idle' | 'Ok' | 'Busy' | 'Alert'
  - vector[membername] → membervalue string (via PropertyVector.__getitem__)
  - SwitchVector: membervalue is 'On' or 'Off'
  - NumberVector: membervalue is a formatted string; use getfloatvalue(name) for float
  - BLOBVector:   membervalue is bytes
  - send_newVector(device, vector, members={name: value})
  - asyncrun() must be running (as a Task) for any I/O to happen.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog
from indipyclient import IPyClient
from indipyclient import events as indi_events

logger = structlog.get_logger()


@dataclass
class BlobData:
    """Received BLOB payload."""
    data: bytes
    format: str   # file extension, e.g. '.fits'


class IndiClient(IPyClient):
    """
    Async INDI client for astrolol device adapters.

    Subclasses IPyClient and adds higher-level wait primitives used by
    mount.py, focuser.py, and camera.py.

    Usage::

        client = IndiClient(host="localhost", port=7624)
        await client.connect()
        await client.connect_device("Telescope Simulator")
        # … use client …
        await client.disconnect()
    """

    def __init__(self, host: str = "localhost", port: int = 7624) -> None:
        super().__init__(indihost=host, indiport=port)
        self.host = host
        self.port = port
        # Asyncio primitives are created in connect() so they bind to the
        # event loop that is actually running at connection time.  Creating
        # them here would bind them to whatever loop happens to be current
        # (or None) when the object is instantiated — a problem when the
        # same IndiClient is reused across different event loops (e.g. in
        # tests where each function gets its own loop).
        self._cond: asyncio.Condition | None = None
        self._connected: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._blob_versions: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start asyncrun() and wait for the TCP connection to be established."""
        # (Re-)create primitives bound to the current running loop.
        self._cond = asyncio.Condition()
        self._connected = asyncio.Event()
        self._blob_versions.clear()
        self._task = asyncio.create_task(self.asyncrun())
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            self.shutdown()
            raise ConnectionError(
                f"Could not connect to indiserver at {self.host}:{self.port}"
            )
        logger.info("indi.client_connected", host=self.host, port=self.port)

    async def disconnect(self) -> None:
        """Shut down asyncrun() and wait for it to finish."""
        self.shutdown()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------
    # IPyClient overrides
    # ------------------------------------------------------------------

    async def rxevent(self, event: Any) -> None:  # noqa: ANN401
        if self._connected is not None:
            if isinstance(event, indi_events.ConnectionMade):
                self._connected.set()
            elif isinstance(event, indi_events.ConnectionLost):
                self._connected.clear()

        if isinstance(event, indi_events.setBLOBVector):
            key = (event.devicename, event.vectorname)
            self._blob_versions[key] = self._blob_versions.get(key, 0) + 1

        if self._cond is not None:
            async with self._cond:
                self._cond.notify_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_vector(self, device_name: str, prop_name: str) -> Any | None:
        device = self.data.get(device_name)
        if device is None:
            return None
        return device.data.get(prop_name)

    def _vector_state(self, device_name: str, prop_name: str) -> str | None:
        v = self._get_vector(device_name, prop_name)
        return v.state if v is not None else None

    async def _wait_cond(self, predicate: Any, timeout: float) -> None:
        """Wait until predicate() is True, or raise TimeoutError."""
        assert self._cond is not None, "IndiClient.connect() must be called first"
        deadline = asyncio.get_event_loop().time() + timeout
        async with self._cond:
            while not predicate():
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f"Condition not met within {timeout}s")
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    pass  # loop will re-check deadline

    # ------------------------------------------------------------------
    # Device lifecycle
    # ------------------------------------------------------------------

    async def connect_device(
        self,
        device_name: str,
        *,
        prop_timeout: float = 10.0,
        conn_timeout: float = 25.0,
        pre_connect_props: dict[str, dict] | None = None,
    ) -> None:
        """Connect an INDI device and wait for its full property set to appear.

        Args:
            device_name:       INDI device name (e.g. "EQMod Mount").
            prop_timeout:      seconds to wait for the driver to announce CONNECTION.
            conn_timeout:      seconds to wait for CONNECTION to reach Ok after
                               sending CONNECT.  Real hardware (serial mounts,
                               focusers) often needs 15–25 s for initialisation.
            pre_connect_props: properties to set before sending CONNECT.
                               Format: {prop_name: {"values": {elem: val}} or
                                                   {"on_elements": [elem, ...]}}
                               Text vs number is auto-detected from the live vector.
        """
        # Step 1: wait for the device and its CONNECTION property to be announced.
        await self.wait_for_property(device_name, "CONNECTION", timeout=prop_timeout)

        # Step 1b: apply caller-specified pre-connect properties (e.g. DEVICE_PORT).
        if pre_connect_props:
            for prop_name, spec in pre_connect_props.items():
                try:
                    await self.wait_for_property(device_name, prop_name, timeout=2.0)
                    if "on_elements" in spec:
                        await self.set_switch(device_name, prop_name, spec["on_elements"])
                    elif "values" in spec:
                        v = self._get_vector(device_name, prop_name)
                        if v is not None and v.vectortype == "NumberVector":
                            await self.set_number(
                                device_name, prop_name,
                                {k: float(val) for k, val in spec["values"].items()},
                            )
                        else:
                            await self.set_text(
                                device_name, prop_name,
                                {k: str(val) for k, val in spec["values"].items()},
                            )
                    logger.info("indi.pre_connect_prop_set", device=device_name, prop=prop_name)
                except Exception as exc:
                    logger.warning(
                        "indi.pre_connect_prop_failed",
                        device=device_name, prop=prop_name, error=str(exc),
                    )

        # Step 2: send CONNECTION=CONNECT.
        await self.set_switch(device_name, "CONNECTION", ["CONNECT"])

        # Step 3: wait for CONNECTION to reach Ok with CONNECT=On.
        await self._wait_cond(
            lambda: (
                self._vector_state(device_name, "CONNECTION") == "Ok"
                and self._get_vector(device_name, "CONNECTION") is not None
                and self._get_vector(device_name, "CONNECTION")["CONNECT"] == "On"
            ),
            timeout=conn_timeout,
        )
        # Step 4: let the initial defXxxVector flood drain.  In asyncio the
        # event loop processes pending data during the sleep, so 150 ms of
        # silence is enough to guarantee all properties are known before we
        # send the first command.
        await asyncio.sleep(0.15)
        logger.info("indi.device_connected", device=device_name)

    async def disconnect_device(self, device_name: str) -> None:
        await self.set_switch(device_name, "CONNECTION", ["DISCONNECT"])
        logger.info("indi.device_disconnected", device=device_name)

    # ------------------------------------------------------------------
    # Property access
    # ------------------------------------------------------------------

    async def wait_for_property(
        self, device_name: str, prop_name: str, timeout: float = 10.0
    ) -> Any:
        """Wait until a property vector is known and return it."""
        await self._wait_cond(
            lambda: self._get_vector(device_name, prop_name) is not None,
            timeout=timeout,
        )
        return self._get_vector(device_name, prop_name)

    async def get_number(
        self, device_name: str, prop_name: str, element: str
    ) -> float:
        v = await self.wait_for_property(device_name, prop_name)
        return v.getfloatvalue(element)

    async def get_switch_state(
        self, device_name: str, prop_name: str, element: str
    ) -> bool:
        v = await self.wait_for_property(device_name, prop_name)
        val = v.data.get(element)
        if val is None:
            raise KeyError(f"Element {element} not found in {device_name}/{prop_name}")
        return val.membervalue == "On"

    async def get_properties_snapshot(self, device_name: str) -> dict[str, Any]:
        device = self.data.get(device_name)
        if device is None:
            return {}
        return dict(device.data)

    def get_messages(self, device_name: str) -> list[dict[str, str]]:
        """Return device messages as a list of {timestamp, message} dicts, newest first."""
        device = self.data.get(device_name)
        if device is None:
            return []
        return [
            {"timestamp": ts.isoformat(), "message": msg}
            for ts, msg in device.messages
        ]

    # ------------------------------------------------------------------
    # Sending commands
    # ------------------------------------------------------------------

    async def set_number(
        self, device_name: str, prop_name: str, values: dict[str, float]
    ) -> None:
        await self.send_newVector(device_name, prop_name, members=values)

    async def set_switch(
        self, device_name: str, prop_name: str, on_elements: list[str]
    ) -> None:
        v = await self.wait_for_property(device_name, prop_name)
        members = {name: ("On" if name in on_elements else "Off") for name in v.data}
        await self.send_newVector(device_name, prop_name, members=members)

    async def set_text(
        self, device_name: str, prop_name: str, values: dict[str, str]
    ) -> None:
        await self.send_newVector(device_name, prop_name, members=values)

    async def enable_blob(self, device_name: str) -> None:
        await self.send_enableBLOB("Also", device_name)

    # ------------------------------------------------------------------
    # Waiting for state transitions
    # ------------------------------------------------------------------

    async def wait_for_blob(
        self, device_name: str, prop_name: str, timeout: float = 60.0
    ) -> BlobData:
        """Wait for a new BLOB to arrive and return its data and format."""
        key = (device_name, prop_name)
        seen = self._blob_versions.get(key, 0)
        await self._wait_cond(
            lambda: self._blob_versions.get(key, 0) > seen,
            timeout=timeout,
        )
        v = self._get_vector(device_name, prop_name)
        if v is None:
            raise RuntimeError(f"BLOB vector {device_name}/{prop_name} not found")
        first = next(iter(v.data.values()))
        return BlobData(data=first.membervalue, format=first.blobformat)

    async def wait_prop_not_busy(
        self, device_name: str, prop_name: str, timeout: float = 120.0
    ) -> None:
        await self._wait_cond(
            lambda: self._vector_state(device_name, prop_name) not in (None, "Busy"),
            timeout=timeout,
        )

    async def wait_prop_busy_then_done(
        self,
        device_name: str,
        prop_name: str,
        busy_timeout: float = 2.0,
        done_timeout: float = 120.0,
    ) -> None:
        """Wait for a property to enter Busy, then wait for it to leave Busy."""
        # Phase 1: wait for Busy (up to busy_timeout; skip if instantaneous)
        went_busy = False
        deadline = asyncio.get_event_loop().time() + busy_timeout
        async with self._cond:
            while True:
                if self._vector_state(device_name, prop_name) == "Busy":
                    went_busy = True
                    break
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
        if not went_busy:
            return
        # Phase 2: wait for Busy to end
        await self.wait_prop_not_busy(device_name, prop_name, timeout=done_timeout)

    async def wait_for_switch_on(
        self,
        device_name: str,
        prop_name: str,
        element: str,
        timeout: float = 120.0,
        interval: float = 0.5,
    ) -> None:
        """Poll until a switch element becomes On."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(interval)
            try:
                if await self.get_switch_state(device_name, prop_name, element):
                    return
            except Exception:
                pass
        raise TimeoutError(
            f"Switch {device_name}/{prop_name}/{element} did not turn On within {timeout}s"
        )

    async def wait_for_switch_off(
        self,
        device_name: str,
        prop_name: str,
        element: str,
        timeout: float = 120.0,
        interval: float = 0.5,
    ) -> None:
        """Poll until a switch element becomes Off."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(interval)
            try:
                if not await self.get_switch_state(device_name, prop_name, element):
                    return
            except Exception:
                pass
        raise TimeoutError(
            f"Switch {device_name}/{prop_name}/{element} did not turn Off within {timeout}s"
        )
