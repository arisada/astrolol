from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.devices.config import DeviceConfig
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

def find_profile_site(profile: Profile, equipment_store: EquipmentStore) -> SiteItem | None:
    """Return the first Site item in the profile's equipment tree, or None."""
    stack = list(profile.roots)
    while stack:
        node = stack.pop(0)
        try:
            item = equipment_store.get(node.item_id)
        except KeyError:
            item = None
        if isinstance(item, SiteItem):
            return item
        stack.extend(node.children)
    return None


def _clean_params(params: dict) -> dict:
    return {k: v for k, v in params.items() if k != "pre_connect_props"}


def _find_device_for_item(device_manager, kind: str, item: EquipmentItem):
    """Return the adapter instance for a connected device matching this inventory item."""
    entry = _find_entry_for_item(device_manager, kind, item)
    return entry.instance if entry is not None else None


def _find_entry_for_item(device_manager, kind: str, item: EquipmentItem):
    """Return the DeviceManager entry for a connected device matching this inventory item.

    INDI-family items match by the driver's own announced device_name — stable
    across reconnects even if astrolol's device_id changes, see astrolol/api/indi.py.
    Any other adapter (e.g. plugins/eqmod's native, non-INDI mount) has no such
    driver-announced identity, so it matches by adapter_key + exact connect_params
    equality instead — there's no single params key that means "identity" across
    arbitrary adapters, so the full params dict is the only adapter-agnostic option.
    """
    indi_name = getattr(item, "indi_device_name", None)
    adapter_key = getattr(item, "adapter_key", None)
    connect_params = _clean_params(getattr(item, "connect_params", None) or {})

    for entry in device_manager._devices.values():
        if entry.config.kind != kind:
            continue
        if indi_name and entry.config.params.get("device_name") == indi_name:
            return entry
        if adapter_key and entry.config.adapter_key == adapter_key:
            if _clean_params(entry.config.params) == connect_params:
                return entry
    return None


_CONNECTABLE_KINDS = frozenset({"mount", "camera", "focuser", "filter_wheel", "rotator"})


def item_device_config(item: EquipmentItem, device_id: str | None = None) -> DeviceConfig | None:
    """Connection config for an inventory item, or None if it carries no connection info."""
    if item.type not in _CONNECTABLE_KINDS:
        return None
    device_id = device_id or _device_id_for_item(item)
    adapter_key = getattr(item, "adapter_key", None)
    if adapter_key:
        return DeviceConfig(
            device_id=device_id, kind=item.type, adapter_key=adapter_key,
            params=dict(getattr(item, "connect_params", None) or {}),
        )
    indi_driver = getattr(item, "indi_driver", None)
    indi_name = getattr(item, "indi_device_name", None)
    if indi_driver and indi_name:
        # The INDI adapters load the driver themselves when given its executable.
        return DeviceConfig(
            device_id=device_id, kind=item.type, adapter_key=f"indi_{item.type}",
            params={"device_name": indi_name, "executable": indi_driver},
        )
    return None


def _device_id_for_item(item: EquipmentItem) -> str:
    """Stable across restarts (per-device settings are keyed by device_id)."""
    slug = re.sub(r"[^a-z0-9]+", "_", item.name.lower()).strip("_")[:40]  # type: ignore[union-attr]
    return f"{item.type}_{slug}" if slug else f"{item.type}_{item.id[:8]}"  # type: ignore[union-attr]


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

    Items already connected (e.g. through the Equipment wizard) are reported, not reconnected.
    Newly connected mounts get the site/time pushed and their automation loop started.
    """
    equipment_store: EquipmentStore | None = getattr(state, "equipment_store", None)
    if equipment_store is None or not profile.roots:
        return [], []
    device_manager = state.device_manager
    mount_manager = getattr(state, "mount_manager", None)
    site = find_profile_site(profile, equipment_store)
    connected: list[DeviceResult] = []
    failed: list[DeviceResult] = []
    used_ids: set[str] = set()

    for item in _tree_items(profile, equipment_store):
        device_id = _device_id_for_item(item)
        if device_id in used_ids:
            device_id = f"{device_id}_{item.id[:8]}"  # type: ignore[union-attr]
        config = item_device_config(item, device_id)
        if config is None:
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
        if config.kind == "mount" and mount_manager is not None:
            await mount_manager.push_site_data(config.device_id, site)
            mount_manager.start_automation(config.device_id)
    return connected, failed


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
            mount = _find_device_for_item(device_manager, "mount", item)
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
                        item_id=item.id, error=str(exc),  # type: ignore[union-attr]
                    )

        elif item.type == "ota":
            current_ota = item  # type: ignore[assignment]

        elif item.type == "camera" and current_ota is not None:
            camera = _find_device_for_item(device_manager, "camera", item)
            if camera is not None and hasattr(camera, "push_scope_info"):
                try:
                    await camera.push_scope_info(
                        current_ota.focal_length,
                        current_ota.aperture,
                    )
                except Exception as exc:
                    logger.warning(
                        "profile.push_scope_info_failed",
                        item_id=item.id, error=str(exc),  # type: ignore[union-attr]
                    )

        # Recurse into children, propagating the updated context
        await _apply_tree_context(
            node.children,
            equipment_store,
            device_manager,
            site=current_site,
            ota=current_ota,
        )


async def _push_live_context(
    nodes: list[ProfileNode],
    equipment_store: EquipmentStore,
    device_manager,
    *,
    mount_adapter=None,
) -> None:
    """Walk the equipment tree and push live mount coordinates to cameras.

    Called before each exposure so the camera's TELESCOPE_EOD_COORD INDI
    property matches the mount's actual pointing when the shutter opens.
    Also returns the first mount adapter found (for the caller to use as
    a coord snapshot for FITS header patching).

    Propagates downward: a mount node sets the current mount adapter in
    context; any camera in its subtree receives the coordinate push.
    """
    for node in nodes:
        try:
            item: EquipmentItem = equipment_store.get(node.item_id)
        except KeyError:
            await _push_live_context(
                node.children, equipment_store, device_manager,
                mount_adapter=mount_adapter,
            )
            continue

        current_mount = mount_adapter

        if item.type == "mount":
            adapter = _find_device_for_item(device_manager, "mount", item)
            if adapter is not None:
                current_mount = adapter

        elif item.type == "camera" and current_mount is not None:
            camera = _find_device_for_item(device_manager, "camera", item)
            if camera is not None and hasattr(camera, "push_telescope_coord"):
                try:
                    status = await current_mount.get_status()
                    await camera.push_telescope_coord(
                        status.ra_jnow, status.dec_jnow
                    )
                except Exception as exc:
                    logger.warning(
                        "profile.push_telescope_coord_failed",
                        item_id=item.id, error=str(exc),  # type: ignore[union-attr]
                    )

        await _push_live_context(
            node.children, equipment_store, device_manager,
            mount_adapter=current_mount,
        )


def _find_mount_for_camera(
    nodes: list[ProfileNode],
    equipment_store: EquipmentStore,
    device_manager,
    camera_indi_name: str,
    *,
    mount_adapter=None,
):
    """Return the mount adapter that is an ancestor of the given camera in the tree.

    Used by the imager to resolve the mount coord snapshot for FITS patching when
    profile.devices is empty (tree-only profiles).  Returns None if not found.
    """
    for node in nodes:
        try:
            item: EquipmentItem = equipment_store.get(node.item_id)
        except KeyError:
            result = _find_mount_for_camera(
                node.children, equipment_store, device_manager,
                camera_indi_name, mount_adapter=mount_adapter,
            )
            if result is not None:
                return result
            continue

        current_mount = mount_adapter

        if item.type == "mount":
            adapter = _find_device_for_item(device_manager, "mount", item)
            if adapter is not None:
                current_mount = adapter

        elif item.type == "camera":
            indi_name = getattr(item, "indi_device_name", None)
            if indi_name == camera_indi_name and current_mount is not None:
                return current_mount

        result = _find_mount_for_camera(
            node.children, equipment_store, device_manager,
            camera_indi_name, mount_adapter=current_mount,
        )
        if result is not None:
            return result

    return None


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

    tree_connected, tree_failed = await connect_tree_devices(profile, request.app.state)
    connected.extend(tree_connected)
    failed.extend(tree_failed)

    # Push context from inventory tree (site → mount location, OTA → camera scope info)
    equipment_store: EquipmentStore | None = getattr(request.app.state, "equipment_store", None)
    if equipment_store is not None and profile.roots:
        try:
            await _apply_tree_context(profile.roots, equipment_store, device_manager)
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
    site = find_profile_site(profile, equipment_store) if equipment_store is not None else None

    for pd in profile.devices:  # legacy flat device list
        try:
            await state.device_manager.connect(pd.config)
            if pd.config.kind == "mount":
                await state.mount_manager.push_site_data(pd.config.device_id, site)
                state.mount_manager.start_automation(pd.config.device_id)
        except Exception as exc:
            logger.warning("startup.device_connect_failed", device_id=pd.config.device_id, error=str(exc))
        else:
            if pd.config.kind == "camera":
                await state.imager_manager.push_scope_info(pd.config.device_id)

    connected, failed = await connect_tree_devices(profile, state)
    logger.info(
        "startup.profile_restored", profile_id=profile.id,
        connected=[d.device_id for d in connected], failed=[d.device_id for d in failed],
    )
