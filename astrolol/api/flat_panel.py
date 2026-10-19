import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from astrolol.core.errors import DeviceNotFoundError, DeviceKindError
from astrolol.devices.base.models import FlatPanelStatus
from astrolol.flat_panel.manager import FlatPanelManager

logger = structlog.get_logger()
router = APIRouter(prefix="/flat_panel", tags=["flat_panel"])


def _manager(request: Request) -> FlatPanelManager:
    return request.app.state.flat_panel_manager


class LightRequest(BaseModel):
    on: bool
    brightness: int | None = Field(default=None, ge=0, description="Level to set before switching on/off.")


@router.get("/{device_id}/status", response_model=FlatPanelStatus)
async def get_status(device_id: str, request: Request) -> FlatPanelStatus:
    try:
        return await _manager(request).get_status(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/cover/open", response_model=FlatPanelStatus)
async def open_cover(device_id: str, request: Request) -> FlatPanelStatus:
    try:
        return await _manager(request).open_cover(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{device_id}/cover/close", response_model=FlatPanelStatus)
async def close_cover(device_id: str, request: Request) -> FlatPanelStatus:
    try:
        return await _manager(request).close_cover(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{device_id}/light", response_model=FlatPanelStatus)
async def set_light(device_id: str, body: LightRequest, request: Request) -> FlatPanelStatus:
    try:
        return await _manager(request).set_light(device_id, body.on, body.brightness)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
