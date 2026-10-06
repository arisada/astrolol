"""Bluetooth Serial plugin API — the human-driven pairing workflow.

GET    /plugins/bluetooth_serial/scan              → discover nearby devices
POST   /plugins/bluetooth_serial/pair               → pair + trust + resolve RFCOMM channel
PATCH  /plugins/bluetooth_serial/paired/{device_id}  → rename
DELETE /plugins/bluetooth_serial/paired/{device_id}  → forget (unpair)

Listing paired devices is core data (GET /devices/bluetooth/paired, see
astrolol/api/bluetooth.py) since other plugins' UIs — eqmod's connection
form, for instance — need it too, not just this plugin's own page.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.devices.bluetooth.backend import BlueZUnavailableError
from astrolol.devices.bluetooth.manager import BluetoothManager
from astrolol.devices.bluetooth.models import DiscoveredDevice, PairedSerialDevice

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/bluetooth_serial", tags=["bluetooth_serial"])

DEFAULT_SCAN_TIMEOUT = 8.0


def _manager(request: Request) -> BluetoothManager:
    return request.app.state.bluetooth_manager


class PairRequest(BaseModel):
    mac: str
    pin: str | None = None
    name: str | None = None


class RenameRequest(BaseModel):
    name: str


@router.get("/scan", response_model=list[DiscoveredDevice])
async def scan(request: Request, timeout: float = DEFAULT_SCAN_TIMEOUT) -> list[DiscoveredDevice]:
    try:
        return await _manager(request).scan(timeout=timeout)
    except BlueZUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/pair", response_model=PairedSerialDevice)
async def pair(request: Request, body: PairRequest) -> PairedSerialDevice:
    try:
        return await _manager(request).pair(body.mac, pin=body.pin, name=body.name)
    except BlueZUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("bluetooth_serial.pair_failed", mac=body.mac, error=str(exc), exc_info=True)
        raise HTTPException(status_code=400, detail=f"Pairing failed: {exc}") from exc


@router.patch("/paired/{device_id}", response_model=PairedSerialDevice)
async def rename(device_id: str, body: RenameRequest, request: Request) -> PairedSerialDevice:
    try:
        return _manager(request).rename(device_id, body.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown device '{device_id}'") from exc


@router.delete("/paired/{device_id}", status_code=204)
async def forget(device_id: str, request: Request) -> None:
    try:
        await _manager(request).forget(device_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown device '{device_id}'") from exc
