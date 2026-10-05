"""Equipment inventory models.

Two concerns live here:
  1. EquipmentItem — the global inventory (hardware you own, independent of any profile).
  2. ProfileNode — a tree node inside a profile that references an inventory item by UUID.
"""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Inventory items (discriminated union on "type")
# ---------------------------------------------------------------------------

class SiteItem(BaseModel):
    id: str = Field(default_factory=_uid)
    type: Literal["site"] = "site"
    name: str
    latitude: float = Field(description="Degrees, positive = North")
    longitude: float = Field(description="Degrees, positive = East")
    altitude: float = Field(default=0.0, description="Metres above sea level")
    timezone: str = Field(default="UTC")


class MountItem(BaseModel):
    id: str = Field(default_factory=_uid)
    type: Literal["mount"] = "mount"
    name: str
    indi_driver: str | None = None
    indi_device_name: str | None = None
    # For non-INDI adapters (e.g. plugins/eqmod's "eqmod_sim"/"eqmod"): the
    # adapter_key + params used to connect, mirroring DeviceConfig. Matched
    # against connected devices by astrolol/api/profiles.py's
    # _find_device_for_item() when indi_device_name is absent.
    adapter_key: str | None = None
    connect_params: dict = {}


class OTAItem(BaseModel):
    id: str = Field(default_factory=_uid)
    type: Literal["ota"] = "ota"
    name: str
    focal_length: float = Field(description="Focal length in mm")
    aperture: float = Field(description="Aperture diameter in mm")


class CameraItem(BaseModel):
    id: str = Field(default_factory=_uid)
    type: Literal["camera"] = "camera"
    name: str
    indi_driver: str | None = None
    indi_device_name: str | None = None
    adapter_key: str | None = None
    connect_params: dict = {}
    pixel_size_um: float | None = None
    default_gain: int | None = Field(
        default=None,
        description="Gain to pre-fill for new exposures on this camera. Camera driver "
        "defaults are often not what you want (e.g. a high-gain preset meant for "
        "framing) and using them unnoticed can ruin a night's worth of frames.",
    )


class FilterWheelItem(BaseModel):
    id: str = Field(default_factory=_uid)
    type: Literal["filter_wheel"] = "filter_wheel"
    name: str
    indi_driver: str | None = None
    indi_device_name: str | None = None
    adapter_key: str | None = None
    connect_params: dict = {}
    filter_names: list[str] = []


class FocuserItem(BaseModel):
    id: str = Field(default_factory=_uid)
    type: Literal["focuser"] = "focuser"
    name: str
    indi_driver: str | None = None
    indi_device_name: str | None = None
    adapter_key: str | None = None
    connect_params: dict = {}


class RotatorItem(BaseModel):
    id: str = Field(default_factory=_uid)
    type: Literal["rotator"] = "rotator"
    name: str
    indi_driver: str | None = None
    indi_device_name: str | None = None
    adapter_key: str | None = None
    connect_params: dict = {}


class GpsItem(BaseModel):
    id: str = Field(default_factory=_uid)
    type: Literal["gps"] = "gps"
    name: str
    indi_driver: str | None = None
    indi_device_name: str | None = None
    adapter_key: str | None = None
    connect_params: dict = {}


EquipmentItem = Annotated[
    SiteItem | MountItem | OTAItem | CameraItem |
    FilterWheelItem | FocuserItem | RotatorItem | GpsItem,
    Field(discriminator="type"),
]

# Mapping from parent item type → allowed child item types
VALID_CHILD_TYPES: dict[str, set[str]] = {
    "site": {"mount", "gps"},
    "mount": {"ota"},
    "ota": {"camera", "focuser", "rotator", "filter_wheel", "ota"},
    "focuser": {"filter_wheel", "camera"},
    "filter_wheel": {"camera"},
    "rotator": {"focuser", "filter_wheel", "camera"},
    "camera": set(),
    "gps": set(),
}


# ---------------------------------------------------------------------------
# Profile tree nodes
# ---------------------------------------------------------------------------

class ProfileNode(BaseModel):
    """A node in the profile equipment tree.

    References an inventory item by ``item_id``.  ``role`` distinguishes
    primary/guide/OAG when the same type can appear multiple times under a
    parent (e.g. two OTAs on the same mount).
    """
    item_id: str
    role: str | None = None  # None = primary; "guide", "oag", etc.
    children: list[ProfileNode] = []


# Required for the self-referential model
ProfileNode.model_rebuild()
