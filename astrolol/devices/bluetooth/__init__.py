"""Core Bluetooth-serial infrastructure (bundled, like astrolol/devices/indi/).

This package knows how to pair/trust a classic Bluetooth device and open an
RFCOMM socket to it. It deliberately knows nothing about any specific mount,
focuser or other consumer — adapters depend on it the same way they'd depend
on pyserial, not on a plugin.

Pairing/trust is a one-time, human-driven action (PIN entry) surfaced by the
``bluetooth_serial`` plugin's UI. Once a device is trusted, BlueZ persists the
link key across reboots, so ``BluetoothManager.open()`` never re-triggers
pairing on its own — see ``manager.py``.
"""
from astrolol.devices.bluetooth.manager import BluetoothManager
from astrolol.devices.bluetooth.models import DiscoveredDevice, PairedSerialDevice
from astrolol.devices.bluetooth.transport import BluetoothRfcommTransport

__all__ = [
    "BluetoothManager",
    "BluetoothRfcommTransport",
    "DiscoveredDevice",
    "PairedSerialDevice",
]
