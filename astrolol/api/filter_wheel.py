import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from astrolol.core.errors import DeviceNotFoundError, DeviceKindError
from astrolol.devices.base.models import FilterWheelStatus
from astrolol.filter_wheel.manager import FilterWheelManager

logger = structlog.get_logger()
router = APIRouter(prefix="/filter_wheel", tags=["filter_wheel"])


def _manager(request: Request) -> FilterWheelManager:
    return request.app.state.filter_wheel_manager


class SelectFilterRequest(BaseModel):
    slot: int


@router.get("/{device_id}/status", response_model=FilterWheelStatus)
async def get_status(device_id: str, request: Request) -> FilterWheelStatus:
    try:
        return await _manager(request).get_status(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/select", status_code=204)
async def select_filter(device_id: str, body: SelectFilterRequest, request: Request) -> None:
    try:
        await _manager(request).select_filter(device_id, body.slot)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
