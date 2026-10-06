"""JSON persistence for paired Bluetooth serial devices (same pattern as ProfileStore)."""
from __future__ import annotations

import json
from pathlib import Path

from astrolol.devices.bluetooth.models import PairedSerialDevice


class BluetoothDeviceStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._devices: dict[str, PairedSerialDevice] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._devices = {
                d["id"]: PairedSerialDevice.model_validate(d) for d in data.get("devices", [])
            }
        except Exception:
            pass  # corrupt file — start fresh

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"devices": [d.model_dump(mode="json") for d in self._devices.values()]}
        self._path.write_text(json.dumps(payload, indent=2))

    def list(self) -> list[PairedSerialDevice]:
        return list(self._devices.values())

    def get(self, device_id: str) -> PairedSerialDevice | None:
        return self._devices.get(device_id)

    def put(self, device: PairedSerialDevice) -> None:
        self._devices[device.id] = device
        self._save()

    def delete(self, device_id: str) -> None:
        if device_id in self._devices:
            del self._devices[device_id]
            self._save()
