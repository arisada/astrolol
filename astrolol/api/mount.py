from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import astropy.units as u
from astropy.coordinates import FK5, SkyCoord
from astropy.time import Time

from astrolol.core.errors import DeviceKindError, DeviceNotFoundError
from astrolol.devices.base.models import MountStatus, Target, TrackingMode
from astrolol.mount.manager import MountManager

router = APIRouter(prefix="/mount", tags=["mount"])


def _manager(request: Request) -> MountManager:
    return request.app.state.mount_manager


class TrackingRequest(BaseModel):
    enabled: bool
    mode: TrackingMode | None = None


class TargetRequest(BaseModel):
    """Sky coordinates in degrees. Use frame to specify the coordinate system."""
    ra: float   # degrees
    dec: float  # degrees
    name: str | None = None
    source: str | None = None
    frame: Literal["icrs", "jnow"] = "icrs"


class SyncRequest(BaseModel):
    """ICRS (J2000) coordinates in degrees."""
    ra: float   # ICRS degrees
    dec: float  # ICRS degrees


def _icrs_deg_to_skycoord(ra_deg: float, dec_deg: float) -> SkyCoord:
    return SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")


def _target_request_to_skycoord(body: TargetRequest) -> SkyCoord:
    if body.frame == "jnow":
        return SkyCoord(
            ra=body.ra * u.deg,
            dec=body.dec * u.deg,
            frame=FK5(equinox=Time.now()),
        ).icrs
    return _icrs_deg_to_skycoord(body.ra, body.dec)


@router.get("/{device_id}/status", response_model=MountStatus)
async def status(device_id: str, request: Request) -> MountStatus:
    try:
        return await _manager(request).get_status(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{device_id}/target", response_model=Target, status_code=200)
async def set_target(device_id: str, body: TargetRequest, request: Request) -> Target:
    """Set the current target (ICRS degrees). Returns the stored target."""
    try:
        coord = _target_request_to_skycoord(body)
        return await _manager(request).set_target(device_id, coord, name=body.name, source=body.source)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{device_id}/target", response_model=Target)
async def get_target(device_id: str, request: Request) -> Target:
    """Get the current target, or 404 if none is set."""
    target = _manager(request).get_target(device_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No target set")
    return target


@router.delete("/{device_id}/target", status_code=204)
async def clear_target(device_id: str, request: Request) -> None:
    """Clear the current target."""
    try:
        await _manager(request).clear_target(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{device_id}/slew", status_code=202)
async def slew(device_id: str, request: Request) -> dict[str, str]:
    """Slew to the current target. Returns immediately; subscribe to /ws/events for completion."""
    try:
        await _manager(request).slew(device_id)
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
async def sync(device_id: str, body: SyncRequest, request: Request) -> None:
    """Sync the mount coordinate model to the given ICRS position (degrees)."""
    try:
        await _manager(request).sync(device_id, _icrs_deg_to_skycoord(body.ra, body.dec))
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


@router.post("/{device_id}/set_park_position", status_code=204)
async def set_park_position(device_id: str, request: Request) -> None:
    """Set the current mount position as the park position."""
    try:
        await _manager(request).set_park_position(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class MoveRequest(BaseModel):
    direction: str   # "N" | "S" | "E" | "W"
    rate: str = "centering"  # "guide" | "centering" | "find" | "max"


@router.post("/{device_id}/move", status_code=204)
async def start_move(device_id: str, body: MoveRequest, request: Request) -> None:
    """Start continuous directional motion. Send DELETE /move to stop."""
    try:
        await _manager(request).start_move(device_id, body.direction, body.rate)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{device_id}/move", status_code=204)
async def stop_move(device_id: str, request: Request) -> None:
    """Stop all directional motion started by POST /move."""
    try:
        await _manager(request).stop_move(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
