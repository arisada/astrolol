from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.equipment.models import EquipmentItem
from astrolol.equipment.optical_path import (
    OpticalPath,
    _CONNECTABLE_KINDS,
    _device_id_for_item,
    _find_device_for_item,
    _find_entry_for_item,
    find_profile_site,
    item_device_config,
    resolve_optical_paths,
    walk_mount_sites,
)
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


@router.get("/active/optical-paths", response_model=list[OpticalPath])
async def get_active_optical_paths(request: Request) -> list[OpticalPath]:
    """Per-camera ancestry (mount/site/OTA/focuser/filter-wheel/rotator) resolved from the
    active profile's equipment tree, with live device ids — used by the frontend to wire
    each camera's Imaging panel to the correct focuser/filter wheel instead of guessing."""
    profile: Profile | None = request.app.state.active_profile
    equipment_store: EquipmentStore | None = getattr(request.app.state, "equipment_store", None)
    if profile is None or equipment_store is None or not profile.roots:
        return []
    return resolve_optical_paths(profile, equipment_store, request.app.state.device_manager)


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
        await disconnect_tree_devices(outgoing, request.app.state)
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

def _tree_items(profile: Profile, equipment_store: EquipmentStore) -> list[EquipmentItem]:
    items: list[EquipmentItem] = []
    stack = list(profile.roots)
    while stack:
        node = stack.pop(0)
        try:
            items.append(equipment_store.get(node.item_id))
        except KeyError:
            logger.warning("profile.tree_item_missing", item_id=node.item_id)
        stack.extend(node.children)
    return items


async def connect_tree_devices(profile: Profile, state: Any) -> tuple[list[DeviceResult], list[DeviceResult]]:
    """Connect every connectable inventory item in the profile's equipment tree.

    Items already connected (e.g. through the Equipment wizard) are reported, not
    reconnected. Site/scope-info/automation for the resolved devices is handled
    separately by ``_apply_tree_context``, called by both callers of this function
    right after — so it applies uniformly whether a device was just connected here
    or was already running beforehand. A connectable item with no connection info
    (no adapter_key, and no indi_driver+indi_device_name pair) is reported as failed
    instead of silently vanishing from both lists — that gap used to make a misconfigured
    inventory item (e.g. a focuser added without ever picking its INDI driver) look like
    it simply wasn't part of the profile at all.
    """
    equipment_store: EquipmentStore | None = getattr(state, "equipment_store", None)
    if equipment_store is None or not profile.roots:
        return [], []
    device_manager = state.device_manager
    connected: list[DeviceResult] = []
    failed: list[DeviceResult] = []
    used_ids: set[str] = set()

    for item in _tree_items(profile, equipment_store):
        device_id = _device_id_for_item(item)
        if device_id in used_ids:
            device_id = f"{device_id}_{item.id[:8]}"  # type: ignore[union-attr]
        config = item_device_config(item, device_id)
        if config is None:
            if item.type in _CONNECTABLE_KINDS:
                logger.warning("profile.tree_item_not_connectable", device_id=device_id, kind=item.type)
                failed.append(DeviceResult(
                    device_id=device_id, role=item.type,
                    error="No connection info configured — set its INDI driver/device name "
                    "or adapter in the Equipment page.",
                ))
            continue
        used_ids.add(config.device_id)
        existing = _find_entry_for_item(device_manager, config.kind, item)
        if existing is not None:
            connected.append(DeviceResult(device_id=existing.config.device_id, role=config.kind))
            continue
        try:
            await device_manager.connect(config)
        except Exception as exc:
            logger.warning("profile.device_connect_failed", device_id=config.device_id, error=str(exc))
            failed.append(DeviceResult(device_id=config.device_id, role=config.kind, error=str(exc)))
            continue
        connected.append(DeviceResult(device_id=config.device_id, role=config.kind))
    return connected, failed


async def disconnect_tree_devices(profile: Profile, state: Any) -> None:
    """Disconnect every currently-connected device that matches a connectable inventory
    item in the profile's equipment tree — the disconnect-side counterpart of
    ``connect_tree_devices``, using the same item-to-connected-device matching so a device
    connected via the tree (on activate, on startup restore, or beforehand through the
    Equipment wizard) is fully torn down on deactivate. Mounts also get their automation
    loop stopped, so it doesn't keep polling a device that no longer exists.
    """
    equipment_store: EquipmentStore | None = getattr(state, "equipment_store", None)
    if equipment_store is None or not profile.roots:
        return
    device_manager = state.device_manager
    mount_manager = getattr(state, "mount_manager", None)
    for item in _tree_items(profile, equipment_store):
        entry = _find_entry_for_item(device_manager, item.type, item)
        if entry is None:
            continue
        device_id = entry.config.device_id
        try:
            await device_manager.disconnect(device_id)
        except Exception as exc:
            logger.warning(
                "profile.tree_device_disconnect_failed",
                device_id=device_id, error=str(exc),
            )
        if entry.config.kind == "mount" and mount_manager is not None:
            mount_manager.stop_automation(device_id)


async def _apply_tree_context(
    profile: Profile,
    equipment_store: EquipmentStore,
    device_manager,
    mount_manager=None,
) -> None:
    """Push tree-derived context to every device resolved from the equipment tree.

    - site → mount: UTC time + geographic location (``MountManager.push_site_data``),
      and the mount's automation loop is (re)started (idempotent).
    - OTA → camera: focal length/aperture pushed to the camera's ``SCOPE_INFO``.

    Resolves against *live* connection state each call, so it is safe and cheap to call
    repeatedly — after every ``activate``, on startup restore, and any time a tree-listed
    device reconnects — regardless of whether that device was already connected before
    this call or was just connected by ``connect_tree_devices``.
    """
    if not profile.roots:
        return

    if mount_manager is not None:
        for mount_item, site in walk_mount_sites(profile.roots, equipment_store):
            entry = _find_entry_for_item(device_manager, "mount", mount_item)
            if entry is None:
                continue
            device_id = entry.config.device_id
            try:
                await mount_manager.push_site_data(device_id, site)
            except Exception as exc:
                logger.warning("profile.push_site_data_failed", device_id=device_id, error=str(exc))
            mount_manager.start_automation(device_id)

    paths = resolve_optical_paths(profile, equipment_store, device_manager)
    for path in paths:
        if path.camera_device_id and path.ota is not None:
            try:
                camera = device_manager.get_camera(path.camera_device_id)
            except Exception:
                continue
            push = getattr(camera, "push_scope_info", None)
            if push is not None:
                try:
                    await push(path.ota.focal_length, path.ota.aperture)
                except Exception as exc:
                    logger.warning(
                        "profile.push_scope_info_failed",
                        device_id=path.camera_device_id, error=str(exc),
                    )


def _resolve_active_telescope_name(
    mount_entry, device_manager, eqmod_proxy_status: dict | None,
) -> str | None:
    """The INDI device name a camera should snoop for this resolved mount, or None if
    no INDI device currently carries this mount's live coordinates.

    A real INDI mount is used directly. The native (non-INDI) eqmod adapters only have
    live coordinates reachable over INDI via plugins/eqmod's mount proxy -- and only
    when that proxy is actually running *and* currently relaying this exact mount (the
    proxy always relays whichever connected mount device it finds first, so a proxy
    that's merely enabled doesn't guarantee it's relaying *this* one).
    """
    if mount_entry is None:
        return None
    adapter_key = mount_entry.config.adapter_key
    if adapter_key == "indi_mount":
        return mount_entry.config.params.get("device_name")
    if adapter_key in ("eqmod_sim", "eqmod"):
        if not eqmod_proxy_status or not eqmod_proxy_status.get("enabled") or not eqmod_proxy_status.get("loaded"):
            return None
        connected_mounts = [d for d in device_manager.list_connected() if d["kind"] == "mount" and d["state"] == "connected"]
        if connected_mounts and connected_mounts[0]["device_id"] == mount_entry.config.device_id:
            return eqmod_proxy_status.get("device_name")
    return None


async def _push_live_context(
    nodes: list[ProfileNode],
    equipment_store: EquipmentStore,
    device_manager,
    *,
    mount_adapter=None,
    mount_indi_name: str | None = None,
    eqmod_proxy_status: dict | None = None,
) -> None:
    """Walk the equipment tree and push each camera's mount pointing two ways: a direct
    TELESCOPE_EOD_COORD write (for drivers that expose it) and pointing the driver's own
    ACTIVE_DEVICES.ACTIVE_TELESCOPE at the mount's INDI device (for drivers, including
    the simulator, that only pick up pointing via their native snoop).

    Called before each exposure so the camera reflects the mount's actual pointing when
    the shutter opens.

    Propagates downward: a mount node sets the current mount adapter/INDI name in
    context; any camera in its subtree gets both pushed to it.
    """
    for node in nodes:
        try:
            item: EquipmentItem = equipment_store.get(node.item_id)
        except KeyError:
            await _push_live_context(
                node.children, equipment_store, device_manager,
                mount_adapter=mount_adapter, mount_indi_name=mount_indi_name,
                eqmod_proxy_status=eqmod_proxy_status,
            )
            continue

        current_mount = mount_adapter
        current_mount_indi_name = mount_indi_name

        if item.type == "mount":
            entry = _find_entry_for_item(device_manager, "mount", item)
            if entry is not None:
                current_mount = entry.instance
                current_mount_indi_name = _resolve_active_telescope_name(
                    entry, device_manager, eqmod_proxy_status
                )

        elif item.type == "camera" and current_mount is not None:
            camera = _find_device_for_item(device_manager, "camera", item)
            if camera is not None and hasattr(camera, "push_telescope_coord"):
                try:
                    status = await current_mount.get_status()
                    await camera.push_telescope_coord(status.ra_jnow, status.dec_jnow)
                except Exception as exc:
                    logger.warning(
                        "profile.push_telescope_coord_failed",
                        item_id=item.id, error=str(exc),  # type: ignore[union-attr]
                    )
            if (
                camera is not None
                and current_mount_indi_name is not None
                and hasattr(camera, "set_active_telescope")
            ):
                try:
                    await camera.set_active_telescope(current_mount_indi_name)
                except Exception as exc:
                    logger.warning(
                        "profile.set_active_telescope_failed",
                        item_id=item.id, error=str(exc),  # type: ignore[union-attr]
                    )

        await _push_live_context(
            node.children, equipment_store, device_manager,
            mount_adapter=current_mount, mount_indi_name=current_mount_indi_name,
            eqmod_proxy_status=eqmod_proxy_status,
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
    connected, failed = await connect_tree_devices(profile, request.app.state)

    # Push context from inventory tree (site → mount location/time, OTA → camera scope info)
    equipment_store: EquipmentStore | None = getattr(request.app.state, "equipment_store", None)
    if equipment_store is not None and profile.roots:
        try:
            await _apply_tree_context(
                profile, equipment_store, device_manager,
                mount_manager=getattr(request.app.state, "mount_manager", None),
            )
        except Exception as exc:
            logger.warning("profile.tree_context_failed", error=str(exc))

    return ActivationResult(profile_id=profile_id, connected=connected, failed=failed)


async def restore_last_profile(state: Any) -> None:
    """At startup: re-activate the last active profile and reconnect its devices."""
    store: ProfileStore = state.profile_store
    last_id = store.get_last_active_id()
    if last_id is None:
        return
    try:
        profile = store.get(last_id)
    except KeyError:
        logger.warning("startup.last_profile_not_found", profile_id=last_id)
        return
    state.active_profile = profile
    state.imager_manager.set_context(profile)
    equipment_store: EquipmentStore | None = getattr(state, "equipment_store", None)

    connected, failed = await connect_tree_devices(profile, state)

    if equipment_store is not None and profile.roots:
        try:
            await _apply_tree_context(
                profile, equipment_store, state.device_manager,
                mount_manager=getattr(state, "mount_manager", None),
            )
        except Exception as exc:
            logger.warning("startup.tree_context_failed", error=str(exc))

    logger.info(
        "startup.profile_restored", profile_id=profile.id,
        connected=[d.device_id for d in connected], failed=[d.device_id for d in failed],
    )
