from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from astrolol.core.errors import DeviceNotFoundError, DeviceKindError
from astrolol.devices.base.models import CameraStatus
from astrolol.imaging.imager import ImagerManager
from astrolol.imaging.models import ExposureRequest, ExposureResult, ImagerStatus

router = APIRouter(prefix="/imager", tags=["imager"])


def _imager(request: Request) -> ImagerManager:
    return request.app.state.imager_manager


@router.get("/status", response_model=list[ImagerStatus])
async def all_statuses(request: Request) -> list[ImagerStatus]:
    """Status of all known camera imagers."""
    return _imager(request).all_statuses()


@router.get("/{device_id}/status", response_model=ImagerStatus)
async def status(device_id: str, request: Request) -> ImagerStatus:
    return _imager(request).get_status(device_id)


@router.post("/{device_id}/expose", response_model=ExposureResult, status_code=201)
async def expose(device_id: str, body: ExposureRequest, request: Request) -> ExposureResult:
    """Take a single exposure. Blocks until the exposure is complete."""
    try:
        return await _imager(request).expose(device_id, body)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{device_id}/loop", status_code=202)
async def start_loop(device_id: str, body: ExposureRequest, request: Request) -> dict[str, str]:
    """Start a looping exposure sequence. Returns immediately; subscribe to /ws/events for results."""
    try:
        await _imager(request).start_loop(device_id, body)
        return {"status": "looping", "device_id": device_id}
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/{device_id}/loop", status_code=204)
async def stop_loop(device_id: str, request: Request) -> None:
    """Stop a running loop after the current exposure completes."""
    try:
        await _imager(request).stop_loop(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{device_id}/halt", status_code=204)
async def halt(device_id: str, request: Request) -> None:
    """Immediately abort any running exposure and cancel any active loop."""
    try:
        await _imager(request).halt(device_id)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{device_id}/camera_status", response_model=CameraStatus)
async def camera_status(device_id: str, request: Request) -> CameraStatus:
    """Current camera hardware status: temperature, cooler, etc."""
    try:
        camera = _imager(request)._device_manager.get_camera(device_id)
        return await camera.get_status()
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class SetCoolerRequest(BaseModel):
    enabled: bool
    target_temperature: float | None = None


@router.post("/{device_id}/cooler", status_code=204)
async def set_cooler(device_id: str, body: SetCoolerRequest, request: Request) -> None:
    """Enable/disable the camera cooler and optionally set a target temperature."""
    try:
        camera = _imager(request)._device_manager.get_camera(device_id)
        await camera.set_cooler(body.enabled, body.target_temperature)
    except (DeviceNotFoundError, DeviceKindError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/images/{filename}")
async def serve_image(filename: str) -> FileResponse:
    """Serve a JPEG preview by filename (basename only — no subdirectory traversal)."""
    from astrolol.config.settings import settings

    # Reject any path separators in the filename before touching the filesystem
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    images_root = settings.images_dir.resolve()
    path = (images_root / filename).resolve()

    # Verify the resolved path is still inside images_dir
    try:
        path.relative_to(images_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Image '{filename}' not found.")

    media_type = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "application/octet-stream"
    return FileResponse(path, media_type=media_type)
