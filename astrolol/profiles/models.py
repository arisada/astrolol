from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field

from astrolol.equipment.models import ProfileNode


class Telescope(BaseModel):
    name: str
    focal_length: float = Field(description="Focal length in mm")
    aperture: float = Field(description="Aperture diameter in mm")


class Profile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    telescope: Telescope | None = None
    roots: list[ProfileNode] = Field(
        default=[],
        description="Equipment tree roots referencing inventory items by UUID.",
    )
