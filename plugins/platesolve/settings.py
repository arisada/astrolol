"""Plate-solving plugin settings."""
from pydantic import BaseModel


class PlatesolveSettings(BaseModel):
    astap_bin: str = "astap_cli"
    astap_db_path: str = "/opt/astap"
    astap_search_radius: float = 30.0
    astap_tolerance: float = 0.007
    pixel_size_um: float | None = None
    # Exposure settings (shared across browsers)
    exposure_duration: float = 5.0
    binning: int = 1
    after_solve: str = "nothing"  # "nothing" | "sync" | "sync_slew"
