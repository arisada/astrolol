from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.equipment.models import EquipmentItem, OTAItem, SiteItem
from astrolol.equipment.store import EquipmentStore
from astrolol.profiles.models import Profile, ProfileNode
from astrolol.profiles.store import ProfileStore

logger = structlog.get_logger()

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
# Tree-context propagation
# ---------------------------------------------------------------------------

def _find_device_by_indi_name(device_manager, kind: str, indi_device_name: str):
    """Return the adapter instance for a connected device matching kind + INDI device name."""
    for entry in device_manager._devices.values():
        if entry.config.kind == kind:
            if entry.config.params.get("device_name") == indi_device_name:
                return entry.instance
    return None


async def _apply_tree_context(
    nodes: list[ProfileNode],
    equipment_store: EquipmentStore,
    device_manager,
    *,
    site: SiteItem | None = None,
    ota: OTAItem | None = None,
) -> None:
    """Walk the equipment tree and push context-derived values to INDI devices.

    Propagates downward:
    - SiteItem  → sets GEOGRAPHIC_COORD on any mount in its subtree
    - OTAItem   → sets SCOPE_INFO on any camera in its subtree
    """
    for node in nodes:
        try:
            item: EquipmentItem = equipment_store.get(node.item_id)
        except KeyError:
            logger.warning("profile.tree_item_missing", item_id=node.item_id)
            continue

        current_site = site
        current_ota = ota

        if item.type == "site":
            current_site = item  # type: ignore[assignment]

        elif item.type == "mount" and current_site is not None:
            indi_name = getattr(item, "indi_device_name", None)
            if indi_name:
                mount = _find_device_by_indi_name(device_manager, "mount", indi_name)
                if mount is not None and hasattr(mount, "set_location"):
                    try:
                        await mount.set_location(
                            current_site.latitude,
                            current_site.longitude,
                            current_site.altitude,
                        )
                    except Exception as exc:
                        logger.warning(
                            "profile.push_location_failed",
                            device=indi_name, error=str(exc),
                        )

        elif item.type == "ota":
            current_ota = item  # type: ignore[assignment]

        elif item.type == "camera" and current_ota is not None:
            indi_name = getattr(item, "indi_device_name", None)
            if indi_name:
                camera = _find_device_by_indi_name(device_manager, "camera", indi_name)
                if camera is not None and hasattr(camera, "push_scope_info"):
                    try:
                        await camera.push_scope_info(
                            current_ota.focal_length,
                            current_ota.aperture,
                        )
                    except Exception as exc:
                        logger.warning(
                            "profile.push_scope_info_failed",
                            device=indi_name, error=str(exc),
                        )

        # Recurse into children, propagating the updated context
        await _apply_tree_context(
            node.children,
            equipment_store,
            device_manager,
            site=current_site,
            ota=current_ota,
        )


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
            # Strip pre_connect_props when activating a saved profile so that stale
            # or over-broad property overrides don't clobber driver-managed state
            # (e.g. alignment data, calibration parameters).  INDI drivers restore
            # their own configuration from ~/.indi/ at startup — let them do so.
            #
            # TODO: replace with a proper per-device allowlist of properties that are
            # safe to push on each session (e.g. DEVICE_PORT).  Until then, any
            # pre-connect overrides must be set manually through the INDI properties
            # panel; INDI will then persist them in its own config.
            config = pd.config.model_copy(
                update={"params": {**pd.config.params, "pre_connect_props": None}}
            )
            await device_manager.connect(config)
            connected.append(DeviceResult(device_id=device_id, role=pd.role))
        except Exception as exc:
            failed.append(DeviceResult(device_id=device_id, role=pd.role, error=str(exc)))

    # Push context from inventory tree (site → mount location, OTA → camera scope info)
    equipment_store: EquipmentStore | None = getattr(request.app.state, "equipment_store", None)
    if equipment_store is not None and profile.roots:
        try:
            await _apply_tree_context(profile.roots, equipment_store, device_manager)
        except Exception as exc:
            logger.warning("profile.tree_context_failed", error=str(exc))

    return ActivationResult(profile_id=profile_id, connected=connected, failed=failed)
