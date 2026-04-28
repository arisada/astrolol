from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from astrolol.devices.config import DeviceConfig
from astrolol.equipment.models import ProfileNode


class ObserverLocation(BaseModel):
    name: str = ""
    latitude: float = Field(description="Degrees, positive = North")
    longitude: float = Field(description="Degrees, positive = East")
    altitude: float = Field(default=0.0, description="Metres above sea level")


class Telescope(BaseModel):
    name: str
    focal_length: float = Field(description="Focal length in mm")
    aperture: float = Field(description="Aperture diameter in mm")


class ProfileDevice(BaseModel):
    role: Literal["camera", "mount", "focuser", "filter_wheel", "rotator", "indi"]
    config: DeviceConfig


class Profile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    location: ObserverLocation | None = None
    telescope: Telescope | None = None
    devices: list[ProfileDevice] = []
    roots: list[ProfileNode] = Field(
        default=[],
        description="Equipment tree roots referencing inventory items by UUID.",
    )
