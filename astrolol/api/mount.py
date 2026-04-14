from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.core.errors import DeviceKindError, DeviceNotFoundError
from astrolol.devices.base.models import MountStatus, SlewTarget, TrackingMode
from astrolol.mount.manager import MountManager

router = APIRouter(prefix="/mount", tags=["mount"])


def _manager(request: Request) -> MountManager:
    return request.app.state.mount_manager


class TrackingRequest(BaseModel):
    enabled: bool
    mode: TrackingMode | None = None


@router.get("/{device_id}/status", response_model=MountStatus)
async def status(device_id: str, request: Request) -> MountStatus:
    try:
        return await _manager(request).get_status(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/slew", status_code=202)
async def slew(device_id: str, target: SlewTarget, request: Request) -> dict[str, str]:
    """Start a slew. Returns immediately; subscribe to /ws/events for completion."""
    try:
        await _manager(request).slew(device_id, target)
        return {"status": "slewing", "device_id": device_id}
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{device_id}/stop", status_code=204)
async def stop(device_id: str, request: Request) -> None:
    """Abort any active slew or park and halt motors."""
    try:
        await _manager(request).stop(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/park", status_code=202)
async def park(device_id: str, request: Request) -> dict[str, str]:
    """Start parking the mount. Returns immediately."""
    try:
        await _manager(request).park(device_id)
        return {"status": "parking", "device_id": device_id}
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{device_id}/unpark", status_code=204)
async def unpark(device_id: str, request: Request) -> None:
    try:
        await _manager(request).unpark(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/sync", status_code=204)
async def sync(device_id: str, target: SlewTarget, request: Request) -> None:
    try:
        await _manager(request).sync(device_id, target)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/tracking", status_code=204)
async def set_tracking(device_id: str, body: TrackingRequest, request: Request) -> None:
    try:
        await _manager(request).set_tracking(device_id, body.enabled, body.mode)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/meridian_flip", status_code=202)
async def meridian_flip(device_id: str, request: Request) -> dict[str, str]:
    """Start a meridian flip. Returns immediately; subscribe to /ws/events for completion."""
    try:
        await _manager(request).meridian_flip(device_id)
        return {"status": "flipping", "device_id": device_id}
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
