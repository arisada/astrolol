from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.profiles.models import Profile
from astrolol.profiles.store import ProfileStore

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _store(request: Request) -> ProfileStore:
    return request.app.state.profile_store


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[Profile])
async def list_profiles(request: Request) -> list[Profile]:
    return _store(request).list()


@router.post("", response_model=Profile, status_code=201)
async def create_profile(profile: Profile, request: Request) -> Profile:
    return _store(request).create(profile)


@router.get("/active", response_model=Profile | None)
async def get_active(request: Request) -> Profile | None:
    return request.app.state.active_profile


@router.get("/{profile_id}", response_model=Profile)
async def get_profile(profile_id: str, request: Request) -> Profile:
    try:
        return _store(request).get(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found.")


@router.put("/{profile_id}", response_model=Profile)
async def update_profile(profile_id: str, profile: Profile, request: Request) -> Profile:
    if profile.id != profile_id:
        raise HTTPException(status_code=400, detail="Profile id in URL and body must match.")
    try:
        return _store(request).update(profile)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found.")


# ---------------------------------------------------------------------------
# Active profile — must come before /{profile_id} routes
# ---------------------------------------------------------------------------

@router.delete("/active", status_code=204)
async def deactivate(request: Request) -> None:
    outgoing: Profile | None = request.app.state.active_profile
    if outgoing is not None:
        device_manager = request.app.state.device_manager
        for pd in outgoing.devices:
            try:
                await device_manager.disconnect(pd.config.device_id)
            except Exception:
                pass  # best-effort — device may already be disconnected
    request.app.state.active_profile = None
    request.app.state.imager_manager.set_context(None)
    _store(request).set_last_active_id(None)


# ---------------------------------------------------------------------------
# Per-profile CRUD (parameterised — registered after static routes)
# ---------------------------------------------------------------------------

@router.delete("/{profile_id}", status_code=204)
async def delete_profile(profile_id: str, request: Request) -> None:
    # Clear active if it was this profile
    if getattr(request.app.state.active_profile, "id", None) == profile_id:
        request.app.state.active_profile = None
        request.app.state.imager_manager.set_context(None)
    try:
        _store(request).delete(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found.")


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

class DeviceResult(BaseModel):
    device_id: str
    role: str
    error: str | None = None


class ActivationResult(BaseModel):
    profile_id: str
    connected: list[DeviceResult]
    failed: list[DeviceResult]


@router.post("/{profile_id}/activate", response_model=ActivationResult)
async def activate_profile(profile_id: str, request: Request) -> ActivationResult:
    """
    Set profile as active and connect all its devices.
    Device connections are best-effort: failures are reported but don't abort activation.
    """
    try:
        profile = _store(request).get(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found.")

    # Store active profile and update observing context for FITS metadata
    request.app.state.active_profile = profile
    request.app.state.imager_manager.set_context(profile)
    _store(request).set_last_active_id(profile_id)

    device_manager = request.app.state.device_manager
    connected: list[DeviceResult] = []
    failed: list[DeviceResult] = []

    for pd in profile.devices:
        device_id = pd.config.device_id
        # Skip if already connected
        if device_id in device_manager._devices:
            connected.append(DeviceResult(device_id=device_id, role=pd.role))
            continue
        try:
            await device_manager.connect(pd.config)
            connected.append(DeviceResult(device_id=device_id, role=pd.role))
        except Exception as exc:
            failed.append(DeviceResult(device_id=device_id, role=pd.role, error=str(exc)))

    return ActivationResult(profile_id=profile_id, connected=connected, failed=failed)
