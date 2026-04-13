from enum import StrEnum
from pydantic import BaseModel, Field


class DeviceState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    BUSY = "busy"
    ERROR = "error"


# --- Camera ---

class ExposureParams(BaseModel):
    duration: float = Field(gt=0, description="Exposure duration in seconds")
    gain: int = Field(default=0, ge=0)
    binning: int = Field(default=1, ge=1, le=4)
    frame_type: str = Field(default="light", description="light | dark | flat | bias")


class Image(BaseModel):
    fits_path: str
    width: int
    height: int
    exposure_duration: float


class CameraStatus(BaseModel):
    state: DeviceState
    temperature: float | None = None
    cooler_on: bool = False
    cooler_power: float | None = None


# --- Mount ---

class SlewTarget(BaseModel):
    ra: float = Field(description="Right Ascension in decimal hours (0–24)")
    dec: float = Field(description="Declination in decimal degrees (-90–90)")


class MountStatus(BaseModel):
    state: DeviceState
    ra: float | None = None
    dec: float | None = None
    alt: float | None = None
    az: float | None = None
    is_tracking: bool = False
    is_parked: bool = False
    is_slewing: bool = False


# --- Focuser ---

class FocuserStatus(BaseModel):
    state: DeviceState
    position: int | None = None
    is_moving: bool = False
    temperature: float | None = None
