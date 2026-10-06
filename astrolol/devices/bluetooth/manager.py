"""BluetoothManager — the one object both the bluetooth_serial plugin (pairing UI)
and any device adapter wanting a Bluetooth-serial transport (eqmod today, a DIY
focuser tomorrow) depend on.

Consumers only ever see a ``PairedSerialDevice.id``. The MAC address and RFCOMM
channel are resolved internally and never need to appear in a device's own
connect params — that's the whole point of keeping pairing out of eqmod's
("or any native driver's) plugin code.
"""
from __future__ import annotations

import asyncio
import socket

import structlog

from astrolol.devices.bluetooth.backend import BluetoothBackend
from astrolol.devices.bluetooth.models import DiscoveredDevice, PairedSerialDevice
from astrolol.devices.bluetooth.store import BluetoothDeviceStore

logger = structlog.get_logger()

# The baseband (ACL) link can take a moment to settle right after pairing, or
# after the peripheral drops and the kernel hasn't noticed yet — an RFCOMM
# connect attempted too early fails with ENETDOWN/EHOSTDOWN even though the
# device is right there. Retry with backoff instead of making every consumer
# (and the person clicking "reconnect" twice) work around it themselves.
OPEN_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0, 2.0)


class BluetoothManager:
    def __init__(self, backend: BluetoothBackend, store: BluetoothDeviceStore) -> None:
        self._backend = backend
        self._store = store

    # --- Pairing (human-driven, one time) ---

    async def scan(self, timeout: float = 8.0) -> list[DiscoveredDevice]:
        paired_macs = {d.mac.upper() for d in self._store.list()}
        found = await self._backend.scan(timeout)
        return [
            DiscoveredDevice(mac=mac, name=name, rssi=rssi, paired=mac.upper() in paired_macs)
            for mac, name, rssi in found
        ]

    async def pair(self, mac: str, pin: str | None = None, name: str | None = None) -> PairedSerialDevice:
        resolved_name, channel = await self._backend.pair(mac, pin)
        device = PairedSerialDevice(
            id=mac.upper(), mac=mac.upper(), name=name or resolved_name, channel=channel,
        )
        self._store.put(device)
        logger.info("bluetooth.paired", mac=device.mac, name=device.name, channel=channel)
        return device

    def list_paired(self) -> list[PairedSerialDevice]:
        return self._store.list()

    def get_paired(self, device_id: str) -> PairedSerialDevice | None:
        return self._store.get(device_id)

    def rename(self, device_id: str, name: str) -> PairedSerialDevice:
        device = self._store.get(device_id)
        if device is None:
            raise KeyError(device_id)
        renamed = device.model_copy(update={"name": name})
        self._store.put(renamed)
        return renamed

    async def forget(self, device_id: str) -> None:
        device = self._store.get(device_id)
        if device is None:
            raise KeyError(device_id)
        await self._backend.forget(device.mac)
        self._store.delete(device_id)
        logger.info("bluetooth.forgotten", mac=device.mac)

    # --- Transport (used by device adapters at connect time) ---

    async def open(self, device_id: str) -> socket.socket:
        """Open a connected RFCOMM socket to a previously paired device.

        Deliberately does NOT attempt to pair: pairing needs a human for the
        PIN/confirmation step, so a missing/lost pairing surfaces as an error
        here rather than silently retrying a pairing flow with no PIN source.
        """
        device = self._store.get(device_id)
        if device is None:
            raise KeyError(
                f"No paired Bluetooth device '{device_id}' — pair it first from the "
                "Bluetooth Serial plugin page."
            )
        if not await self._backend.is_paired(device.mac):
            raise ConnectionError(
                f"'{device.name}' ({device.mac}) is no longer paired at the OS level "
                "(link key missing — re-pair it from the Bluetooth Serial plugin page)."
            )
        last_exc: OSError | None = None
        for attempt, delay in enumerate((0.0, *OPEN_RETRY_DELAYS)):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await self._backend.open_socket(device.mac, device.channel)
            except OSError as exc:
                last_exc = exc
                logger.warning(
                    "bluetooth.open_retry", device_id=device_id, attempt=attempt + 1, error=str(exc)
                )
        raise ConnectionError(
            f"Could not open the RFCOMM link to '{device.name}' ({device.mac}) after "
            f"{len(OPEN_RETRY_DELAYS) + 1} attempts: {last_exc}"
        ) from last_exc
