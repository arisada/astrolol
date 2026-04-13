from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.core.errors import (
    AdapterNotFoundError,
    DeviceAlreadyConnectedError,
    DeviceConnectionError,
    DeviceNotFoundError,
)
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager

router = APIRouter(prefix="/devices", tags=["devices"])


def _manager(request: Request) -> DeviceManager:
    return request.app.state.device_manager


class ConnectResponse(BaseModel):
    device_id: str


@router.get("/available")
async def list_available(request: Request) -> dict[str, list[str]]:
    """List all adapter keys registered by plugins."""
    return request.app.state.registry.all_keys()


@router.get("/connected")
async def list_connected(request: Request) -> list[dict[str, str]]:
    """List all currently connected device instances."""
    return _manager(request).list_connected()


@router.get("/connected/{device_id}/config", response_model=DeviceConfig)
async def get_connected_config(device_id: str, request: Request) -> DeviceConfig:
    """Return the full DeviceConfig (including params) for a connected device."""
    try:
        return _manager(request).get_config(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/connect", response_model=ConnectResponse, status_code=201)
async def connect_device(config: DeviceConfig, request: Request) -> ConnectResponse:
    """Connect a device from a DeviceConfig. Returns the device_id."""
    try:
        device_id = await _manager(request).connect(config)
        return ConnectResponse(device_id=device_id)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DeviceAlreadyConnectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except DeviceConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/connected/{device_id}", status_code=204)
async def disconnect_device(device_id: str, request: Request) -> None:
    """Disconnect a device by its device_id."""
    try:
        await _manager(request).disconnect(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
