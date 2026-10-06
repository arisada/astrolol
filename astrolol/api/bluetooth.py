"""Core read-only API for paired Bluetooth serial devices.

Lives in core (not the bluetooth_serial plugin) because any device adapter's
UI may want to let the user pick a paired device — e.g. eqmod's connection
form. Scanning/pairing/forgetting are human-driven actions owned by the
bluetooth_serial plugin; this endpoint only exposes what's already paired.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from astrolol.devices.bluetooth.models import PairedSerialDevice

router = APIRouter(prefix="/devices/bluetooth", tags=["bluetooth"])


@router.get("/paired", response_model=list[PairedSerialDevice])
async def list_paired(request: Request) -> list[PairedSerialDevice]:
    manager = request.app.state.bluetooth_manager
    return manager.list_paired()
