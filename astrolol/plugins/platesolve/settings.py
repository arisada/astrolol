"""Plate-solving plugin settings."""
from pydantic import BaseModel


class PlatesolveSettings(BaseModel):
    # The ASTAP program and its star database are start-up settings (astap_program,
    # astap_database): what runs on the machine is not set from the UI.
    astap_search_radius: float = 30.0
    astap_tolerance: float = 0.007
    pixel_size_um: float | None = None
    # Exposure settings (shared across browsers)
    exposure_duration: float = 5.0
    binning: int = 1
    after_solve: str = "nothing"  # "nothing" | "sync" | "sync_slew"
    camera_id: str = ""           # device_id of the camera to expose with
