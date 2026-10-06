from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DiscoveredDevice(BaseModel):
    """A device seen during a scan — not necessarily paired yet."""
    mac: str
    name: str
    rssi: int | None = None
    paired: bool = False


class PairedSerialDevice(BaseModel):
    """A classic-Bluetooth SPP device this machine has paired, trusted, and
    resolved an RFCOMM channel for. This is the unit other plugins reference
    by ``id`` — they never see a MAC or channel number."""
    id: str                      # stable key, currently the MAC address
    mac: str
    name: str                    # user-editable; defaults to the advertised name
    channel: int                 # RFCOMM channel, resolved via SDP at pair time
    paired_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class BluetoothLinkStatus(BaseModel):
    """Live status of a paired device's serial link, for status chips/UI."""
    id: str
    name: str
    connected: bool
    last_error: str | None = None
