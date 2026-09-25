import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.core.errors import (
    AdapterNotFoundError,
    DeviceAlreadyConnectedError,
    DeviceConnectionError,
    DeviceNotFoundError,
)
from astrolol.api.profiles import find_profile_site
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager

logger = structlog.get_logger()
router = APIRouter(prefix="/devices", tags=["devices"])


def _manager(request: Request) -> DeviceManager:
    return request.app.state.device_manager


async def _push_mount_site_data(request: Request, device_id: str) -> None:
    """Best-effort: push UTC + active-profile location to a newly connected mount, apply its
    limits and start its automation loop."""
    try:
        mount_manager = getattr(request.app.state, "mount_manager", None)
        if mount_manager is None:
            return
        profile = getattr(request.app.state, "active_profile", None)
        equipment_store = getattr(request.app.state, "equipment_store", None)
        site = (
            find_profile_site(profile, equipment_store)
            if profile is not None and equipment_store is not None
            else None
        )
        await mount_manager.push_site_data(device_id, site)
    except Exception as exc:
        logger.warning("mount.site_data_push_failed", device_id=device_id, error=str(exc))
        return
    # Limits and automation (horizon action, auto flip/park), as for mounts connected from a profile.
    await mount_manager.apply_limits(device_id)
    mount_manager.start_automation(device_id)


async def _push_camera_scope_info(request: Request, device_id: str) -> None:
    """Best-effort: push telescope optics from active profile to camera SCOPE_INFO."""
    try:
        imager_manager = getattr(request.app.state, "imager_manager", None)
        if imager_manager is None:
            return
        await imager_manager.push_scope_info(device_id)
    except Exception as exc:
        logger.warning("camera.scope_info_push_failed", device_id=device_id, error=str(exc))


class ConnectResponse(BaseModel):
    device_id: str


@router.get("/available")
async def list_available(request: Request) -> dict[str, list[str]]:
    """List all adapter keys registered by plugins."""
    return request.app.state.registry.all_keys()


@router.get("/available/{kind}/{adapter_key}/defaults")
async def adapter_defaults(kind: str, adapter_key: str, request: Request) -> dict:
    """Default connect params an adapter suggests (empty if it declares none)."""
    try:
        return request.app.state.registry.default_connect_params(kind, adapter_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/connected")
async def list_connected(request: Request) -> list[dict]:
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
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DeviceAlreadyConnectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except DeviceConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if config.kind == "mount":
        await _push_mount_site_data(request, device_id)
    elif config.kind == "camera":
        await _push_camera_scope_info(request, device_id)
    return ConnectResponse(device_id=device_id)


@router.delete("/connected/{device_id}", status_code=204)
async def disconnect_device(device_id: str, request: Request) -> None:
    """Disconnect and fully remove a device by its device_id."""
    try:
        await _manager(request).disconnect(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/connected/{device_id}/disconnect", status_code=204)
async def soft_disconnect_device(device_id: str, request: Request) -> None:
    """Disconnect device hardware but keep it registered for quick reconnect."""
    try:
        await _manager(request).soft_disconnect(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/connected/{device_id}/reconnect", status_code=204)
async def reconnect_device(device_id: str, request: Request) -> None:
    """Reconnect a previously disconnected (but still registered) device."""
    try:
        await _manager(request).reconnect(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DeviceAlreadyConnectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except DeviceConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    config = _manager(request).get_config(device_id)
    if config.kind == "mount":
        await _push_mount_site_data(request, device_id)
    elif config.kind == "camera":
        await _push_camera_scope_info(request, device_id)
