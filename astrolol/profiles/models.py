from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field

from astrolol.equipment.models import ProfileNode


class Profile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    roots: list[ProfileNode] = Field(
        default=[],
        description="Equipment tree roots referencing inventory items by UUID.",
    )
