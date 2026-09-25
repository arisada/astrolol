"""Resolve the equipment tree into per-camera optical paths.

The equipment tree (``Profile.roots``) is the source of truth for how devices relate
to each other (which site a mount sits at, which OTA a camera is mounted on, which
focuser/filter wheel sit between the OTA and the camera). Several consumers need that
same ancestry — FITS header metadata, INDI ``SCOPE_INFO``/location pushes, and the
Imaging page's per-camera focuser/filter-wheel panels — so it is resolved once here
instead of being re-derived ad hoc by each caller.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel

from astrolol.devices.config import DeviceConfig
from astrolol.equipment.models import (
    CameraItem, EquipmentItem, FilterWheelItem, FocuserItem, MountItem,
    OTAItem, RotatorItem, SiteItem,
)

if TYPE_CHECKING:
    from astrolol.devices.manager import DeviceManager
    from astrolol.equipment.store import EquipmentStore
    from astrolol.profiles.models import Profile, ProfileNode

logger = structlog.get_logger()

_CONNECTABLE_KINDS = frozenset({"mount", "camera", "focuser", "filter_wheel", "rotator"})


class OpticalPath(BaseModel):
    """Everything above one camera in the equipment tree, plus live device ids."""

    camera: CameraItem
    camera_device_id: str | None = None

    mount: MountItem | None = None
    mount_device_id: str | None = None
    site: SiteItem | None = None

    ota: OTAItem | None = None

    focuser: FocuserItem | None = None
    focuser_device_id: str | None = None

    filter_wheel: FilterWheelItem | None = None
    filter_wheel_device_id: str | None = None

    rotator: RotatorItem | None = None
    rotator_device_id: str | None = None


def _clean_params(params: dict) -> dict:
    return {k: v for k, v in params.items() if k != "pre_connect_props"}


def _find_entry_for_item(device_manager: "DeviceManager", kind: str, item: EquipmentItem):
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


def _find_device_for_item(device_manager: "DeviceManager", kind: str, item: EquipmentItem):
    """Return the adapter instance for a connected device matching this inventory item."""
    entry = _find_entry_for_item(device_manager, kind, item)
    return entry.instance if entry is not None else None


def _device_id_for_item(item: EquipmentItem) -> str:
    """Stable across restarts (per-device settings are keyed by device_id)."""
    slug = re.sub(r"[^a-z0-9]+", "_", item.name.lower()).strip("_")[:40]  # type: ignore[union-attr]
    return f"{item.type}_{slug}" if slug else f"{item.type}_{item.id[:8]}"  # type: ignore[union-attr]


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


def walk_optical_paths(
    nodes: list["ProfileNode"],
    equipment_store: "EquipmentStore",
    *,
    site: SiteItem | None = None,
    mount: MountItem | None = None,
    ota: OTAItem | None = None,
    focuser: FocuserItem | None = None,
    filter_wheel: FilterWheelItem | None = None,
    rotator: RotatorItem | None = None,
) -> list[OpticalPath]:
    """Walk the equipment tree, emitting one OpticalPath per camera leaf.

    Pure item-id-level resolution (no device_manager dependency) so it is cheap to
    unit test. Ancestors propagate down the branch they were found on; siblings never
    see each other's ancestors, since each recursive call only passes its own locals on.
    """
    paths: list[OpticalPath] = []
    for node in nodes:
        try:
            item: EquipmentItem = equipment_store.get(node.item_id)
        except KeyError:
            logger.warning("optical_path.tree_item_missing", item_id=node.item_id)
            paths.extend(walk_optical_paths(
                node.children, equipment_store,
                site=site, mount=mount, ota=ota,
                focuser=focuser, filter_wheel=filter_wheel, rotator=rotator,
            ))
            continue

        cur_site, cur_mount, cur_ota = site, mount, ota
        cur_focuser, cur_filter_wheel, cur_rotator = focuser, filter_wheel, rotator

        if item.type == "site":
            cur_site = item  # type: ignore[assignment]
        elif item.type == "mount":
            cur_mount = item  # type: ignore[assignment]
        elif item.type == "ota":
            cur_ota = item  # type: ignore[assignment]
        elif item.type == "focuser":
            cur_focuser = item  # type: ignore[assignment]
        elif item.type == "filter_wheel":
            cur_filter_wheel = item  # type: ignore[assignment]
        elif item.type == "rotator":
            cur_rotator = item  # type: ignore[assignment]
        elif item.type == "camera":
            paths.append(OpticalPath(
                camera=item,  # type: ignore[arg-type]
                mount=cur_mount, site=cur_site, ota=cur_ota,
                focuser=cur_focuser, filter_wheel=cur_filter_wheel, rotator=cur_rotator,
            ))

        paths.extend(walk_optical_paths(
            node.children, equipment_store,
            site=cur_site, mount=cur_mount, ota=cur_ota,
            focuser=cur_focuser, filter_wheel=cur_filter_wheel, rotator=cur_rotator,
        ))
    return paths


def walk_mount_sites(
    nodes: list["ProfileNode"],
    equipment_store: "EquipmentStore",
    *,
    site: SiteItem | None = None,
) -> list[tuple[MountItem, SiteItem | None]]:
    """Every mount in the tree paired with its ancestor site, if any.

    A mount needs no camera underneath it to receive its site/time push, so this is
    kept separate from ``walk_optical_paths`` (which only emits a record per camera leaf).
    """
    results: list[tuple[MountItem, SiteItem | None]] = []
    for node in nodes:
        try:
            item: EquipmentItem = equipment_store.get(node.item_id)
        except KeyError:
            results.extend(walk_mount_sites(node.children, equipment_store, site=site))
            continue

        cur_site = site
        if item.type == "site":
            cur_site = item  # type: ignore[assignment]
        elif item.type == "mount":
            results.append((item, cur_site))  # type: ignore[arg-type]

        results.extend(walk_mount_sites(node.children, equipment_store, site=cur_site))
    return results


def resolve_optical_paths(
    profile: "Profile",
    equipment_store: "EquipmentStore",
    device_manager: "DeviceManager",
) -> list[OpticalPath]:
    """walk_optical_paths(), then fill in the live device id for each connectable role."""
    paths = walk_optical_paths(profile.roots, equipment_store)
    for path in paths:
        path.camera_device_id = _device_id_of(device_manager, "camera", path.camera)
        if path.mount is not None:
            path.mount_device_id = _device_id_of(device_manager, "mount", path.mount)
        if path.focuser is not None:
            path.focuser_device_id = _device_id_of(device_manager, "focuser", path.focuser)
        if path.filter_wheel is not None:
            path.filter_wheel_device_id = _device_id_of(device_manager, "filter_wheel", path.filter_wheel)
        if path.rotator is not None:
            path.rotator_device_id = _device_id_of(device_manager, "rotator", path.rotator)
    return paths


def _device_id_of(device_manager: "DeviceManager", kind: str, item: EquipmentItem) -> str | None:
    entry = _find_entry_for_item(device_manager, kind, item)
    return entry.config.device_id if entry is not None else None


def find_optical_path_for_camera_device(
    paths: list[OpticalPath], camera_device_id: str
) -> OpticalPath | None:
    return next((p for p in paths if p.camera_device_id == camera_device_id), None)


def find_profile_site(profile: "Profile", equipment_store: "EquipmentStore") -> SiteItem | None:
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
