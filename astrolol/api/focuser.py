from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.core.errors import DeviceKindError, DeviceNotFoundError
from astrolol.devices.base.models import FocuserStatus
from astrolol.focuser.manager import FocuserManager

router = APIRouter(prefix="/focuser", tags=["focuser"])


def _manager(request: Request) -> FocuserManager:
    return request.app.state.focuser_manager


class MoveToRequest(BaseModel):
    position: int


class MoveByRequest(BaseModel):
    steps: int


@router.get("/{device_id}/status", response_model=FocuserStatus)
async def status(device_id: str, request: Request) -> FocuserStatus:
    try:
        return await _manager(request).get_status(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/move_to", status_code=202)
async def move_to(device_id: str, body: MoveToRequest, request: Request) -> dict[str, object]:
    """Move to absolute position. Returns immediately; subscribe to /ws/events for completion."""
    try:
        await _manager(request).move_to(device_id, body.position)
        return {"status": "moving", "device_id": device_id, "target_position": body.position}
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{device_id}/move_by", status_code=202)
async def move_by(device_id: str, body: MoveByRequest, request: Request) -> dict[str, object]:
    """Move by relative steps (positive = out, negative = in)."""
    try:
        await _manager(request).move_by(device_id, body.steps)
        return {"status": "moving", "device_id": device_id, "steps": body.steps}
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{device_id}/halt", status_code=204)
async def halt(device_id: str, request: Request) -> None:
    """Stop any in-progress move immediately."""
    try:
        await _manager(request).halt(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
