"""BlueZ backend: D-Bus for discovery/pairing/trust, a raw AF_BLUETOOTH socket
for the actual RFCOMM link.

Split deliberately along that line (see the design discussion in the
bluetooth_serial plugin): BlueZ's D-Bus API is the correct, typed way to do
discovery and pairing (no screen-scraping ``bluetoothctl`` prompts — PIN/
passkey requests arrive as real method calls on a registered Agent1 object).
It has no replacement for creating an RFCOMM *tty* device, but a native driver
doesn't need a tty at all: ``socket.AF_BLUETOOTH``/``BTPROTO_RFCOMM`` gives a
plain stream socket, which is what ``open_socket`` returns.

Everything here is behind the ``BluetoothBackend`` Protocol so it can be
faked in tests without real BlueZ/hardware — the same pattern this repo uses
for cameras/mounts/focusers (``tests/conftest.py``).
"""
from __future__ import annotations

import asyncio
import re
import socket
from typing import Protocol

import structlog

logger = structlog.get_logger()

AGENT_PATH = "/astrolol/bluetooth_agent"
BLUEZ_SERVICE = "org.bluez"
DEFAULT_SPP_CHANNEL = 1  # overwhelmingly common for cheap SPP boards (HC-05/06, etc.)
SDP_LOOKUP_TIMEOUT = 5.0


class BluetoothBackend(Protocol):
    """What ``BluetoothManager`` needs from the OS Bluetooth stack."""

    async def scan(self, timeout: float) -> list[tuple[str, str, int | None]]:
        """Return (mac, name, rssi) tuples seen during a timed discovery window."""
        ...

    async def pair(self, mac: str, pin: str | None) -> tuple[str, int]:
        """Pair, trust, and resolve the SPP RFCOMM channel. Returns (name, channel)."""
        ...

    async def is_paired(self, mac: str) -> bool: ...

    async def forget(self, mac: str) -> None:
        """Unpair/remove the device from BlueZ entirely."""
        ...

    async def open_socket(self, mac: str, channel: int) -> socket.socket:
        """Return a connected RFCOMM socket. Raises OSError on failure."""
        ...


class BlueZUnavailableError(RuntimeError):
    """BlueZ/D-Bus could not be reached (no bluetoothd, no permission, not Linux)."""


class BlueZBackend:
    """Real backend: dbus-next against BlueZ + a raw RFCOMM socket."""

    def __init__(self, adapter_path: str = "/org/bluez/hci0") -> None:
        self._adapter_path = adapter_path
        self._bus = None
        self._agent_registered = False
        self._pending_pins: dict[str, str] = {}

    async def _connect_bus(self):
        if self._bus is not None:
            return self._bus
        try:
            from dbus_next import BusType
            from dbus_next.aio import MessageBus
        except ImportError as exc:
            raise BlueZUnavailableError("dbus-next is not installed") from exc
        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        except Exception as exc:
            raise BlueZUnavailableError(f"Could not connect to the system D-Bus: {exc}") from exc
        return self._bus

    async def _ensure_agent(self) -> None:
        if self._agent_registered:
            return
        bus = await self._connect_bus()
        agent = _build_pairing_agent(self._pending_pins)
        bus.export(AGENT_PATH, agent)
        introspection = await bus.introspect(BLUEZ_SERVICE, "/org/bluez")
        obj = bus.get_proxy_object(BLUEZ_SERVICE, "/org/bluez", introspection)
        agent_manager = obj.get_interface("org.bluez.AgentManager1")
        await agent_manager.call_register_agent(AGENT_PATH, "KeyboardDisplay")
        await agent_manager.call_request_default_agent(AGENT_PATH)
        self._agent_registered = True
        logger.info("bluetooth.agent_registered", path=AGENT_PATH)

    async def _adapter_iface(self):
        bus = await self._connect_bus()
        introspection = await bus.introspect(BLUEZ_SERVICE, self._adapter_path)
        obj = bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
        return obj.get_interface("org.bluez.Adapter1")

    async def _device_path(self, mac: str) -> str:
        return f"{self._adapter_path}/dev_{mac.upper().replace(':', '_')}"

    async def _device_iface(self, mac: str):
        bus = await self._connect_bus()
        path = await self._device_path(mac)
        introspection = await bus.introspect(BLUEZ_SERVICE, path)
        obj = bus.get_proxy_object(BLUEZ_SERVICE, path, introspection)
        return obj.get_interface("org.bluez.Device1"), obj.get_interface(
            "org.freedesktop.DBus.Properties"
        )

    async def scan(self, timeout: float) -> list[tuple[str, str, int | None]]:
        await self._ensure_agent()
        bus = await self._connect_bus()
        adapter = await self._adapter_iface()
        await adapter.call_start_discovery()
        try:
            await asyncio.sleep(timeout)
        finally:
            try:
                await adapter.call_stop_discovery()
            except Exception:
                pass

        introspection = await bus.introspect(BLUEZ_SERVICE, "/")
        root = bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        om = root.get_interface("org.freedesktop.DBus.ObjectManager")
        objects = await om.call_get_managed_objects()

        found: list[tuple[str, str, int | None]] = []
        for path, interfaces in objects.items():
            dev = interfaces.get("org.bluez.Device1")
            if dev is None or not path.startswith(self._adapter_path + "/"):
                continue
            mac = dev["Address"].value
            name = dev.get("Alias", dev.get("Name"))
            name = name.value if name is not None else mac
            rssi = dev.get("RSSI")
            found.append((mac, name, rssi.value if rssi is not None else None))
        return found

    async def pair(self, mac: str, pin: str | None) -> tuple[str, int]:
        await self._ensure_agent()
        if pin is not None:
            self._pending_pins[mac.upper()] = pin
        device, props = await self._device_iface(mac)
        try:
            paired = (await props.call_get("org.bluez.Device1", "Paired")).value
            if not paired:
                await device.call_pair()
            await props.call_set("org.bluez.Device1", "Trusted", _bool_variant(True))
            await device.call_connect()
            name = (await props.call_get("org.bluez.Device1", "Alias")).value
        finally:
            self._pending_pins.pop(mac.upper(), None)
        channel = await self._discover_spp_channel(mac)
        return name or mac, channel

    async def is_paired(self, mac: str) -> bool:
        try:
            _, props = await self._device_iface(mac)
            return bool((await props.call_get("org.bluez.Device1", "Paired")).value)
        except Exception:
            return False

    async def forget(self, mac: str) -> None:
        adapter = await self._adapter_iface()
        path = await self._device_path(mac)
        try:
            await adapter.call_remove_device(path)
        except Exception as exc:
            logger.warning("bluetooth.forget_failed", mac=mac, error=str(exc))

    async def _discover_spp_channel(self, mac: str) -> int:
        """Resolve the RFCOMM channel for the Serial Port Profile via sdptool.

        Falls back to the near-universal default (1) if sdptool is unavailable
        or the device doesn't answer in time — most SPP boards only ever
        expose one channel anyway.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "sdptool", "search", "--bdaddr", mac, "SP",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=SDP_LOOKUP_TIMEOUT)
        except (FileNotFoundError, asyncio.TimeoutError, OSError) as exc:
            logger.warning("bluetooth.sdp_lookup_failed", mac=mac, error=str(exc),
                            fallback_channel=DEFAULT_SPP_CHANNEL)
            return DEFAULT_SPP_CHANNEL
        match = re.search(rb"Channel:\s*(\d+)", stdout)
        if not match:
            logger.info("bluetooth.sdp_channel_not_found", mac=mac, fallback_channel=DEFAULT_SPP_CHANNEL)
            return DEFAULT_SPP_CHANNEL
        return int(match.group(1))

    async def open_socket(self, mac: str, channel: int) -> socket.socket:
        loop = asyncio.get_running_loop()

        def _connect() -> socket.socket:
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.connect((mac, channel))
            return sock

        return await loop.run_in_executor(None, _connect)


def _bool_variant(value: bool):
    from dbus_next import Variant
    return Variant("b", value)


def _build_pairing_agent(pending_pins: dict[str, str]):
    """Build an org.bluez.Agent1 ServiceInterface instance.

    Answers PIN/passkey requests with the PIN supplied to
    ``BluetoothManager.pair()`` instead of an interactive prompt — this is
    the whole reason to use the D-Bus agent API over scripting
    ``bluetoothctl``: the request arrives as a typed method call we can
    answer programmatically, not a text prompt we have to pattern-match.
    """
    from dbus_next.service import ServiceInterface, method

    class _Agent(ServiceInterface):
        def __init__(self) -> None:
            super().__init__("org.bluez.Agent1")

        @method()
        def RequestPinCode(self, device: "o") -> "s":  # noqa: N802, F821
            return pending_pins.get(_mac_from_device_path(device), "0000")

        @method()
        def RequestPasskey(self, device: "o") -> "u":  # noqa: N802, F821
            pin = pending_pins.get(_mac_from_device_path(device), "0000")
            return int(pin) if pin.isdigit() else 0

        # dbus_next infers the D-Bus signature from the annotation and rejects
        # anything that isn't a type-string constant — including "-> None" for a
        # void method. These must be left unannotated, not annotated as None.
        @method()
        def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802, F821
            return None  # auto-confirm; SSP "just works" devices need no PIN

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802, F821
            pass

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802, F821
            pass

        @method()
        def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802, F821
            return None

        @method()
        def Cancel(self):  # noqa: N802
            pass

        @method()
        def Release(self):  # noqa: N802
            pass

    return _Agent()


def _mac_from_device_path(path: str) -> str:
    # .../dev_AA_BB_CC_DD_EE_FF -> AA:BB:CC:DD:EE:FF
    segment = path.rsplit("/", 1)[-1]
    if segment.startswith("dev_"):
        return segment[len("dev_"):].replace("_", ":")
    return segment
