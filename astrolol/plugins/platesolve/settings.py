"""Plate-solving plugin settings."""
from typing import Literal

from pydantic import BaseModel


class PlatesolveSettings(BaseModel):
    # Which solver runs. Each program and its star data are start-up settings
    # (astap_program / astap_database, asterion_program / asterion_catalog_dir).
    engine: Literal["astap", "asterion"] = "astap"
    # When the chosen solver finds nothing, try the other one before giving up.
    fallback: bool = True
    astap_search_radius: float = 30.0
    astap_tolerance: float = 0.007
    pixel_size_um: float | None = None
    # Exposure settings (shared across browsers)
    exposure_duration: float = 5.0
    binning: int = 1
    after_solve: str = "nothing"  # "nothing" | "sync" | "sync_slew"
    camera_id: str = ""           # device_id of the camera to expose with
