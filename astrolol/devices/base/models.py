from enum import StrEnum
from pydantic import BaseModel, Field


class DeviceState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    BUSY = "busy"
    ERROR = "error"


class TrackingMode(StrEnum):
    SIDEREAL = "sidereal"
    LUNAR = "lunar"
    SOLAR = "solar"


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
    """HTTP/JSON body for slew and sync requests. Coordinates are ICRS (J2000)."""
    ra: float = Field(description="ICRS Right Ascension in decimal hours (0–24)")
    dec: float = Field(description="ICRS Declination in decimal degrees (-90–90)")


class MountStatus(BaseModel):
    state: DeviceState
    ra: float | None = None    # ICRS decimal hours
    dec: float | None = None   # ICRS decimal degrees
    alt: float | None = None
    az: float | None = None
    is_tracking: bool = False
    is_parked: bool = False
    is_slewing: bool = False
    pier_side: str | None = None    # "East" | "West" — which side of the pier the OTA is on
    hour_angle: float | None = None   # decimal hours, negative = east (pre-meridian), positive = west (post)
    lst: float | None = None           # Local Sidereal Time in decimal hours

    @property
    def skycoord(self) -> "SkyCoord | None":
        """Return current position as an ICRS SkyCoord, or None if unknown."""
        if self.ra is None or self.dec is None:
            return None
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        return SkyCoord(ra=self.ra * u.hourangle, dec=self.dec * u.deg, frame="icrs")


# --- Focuser ---

class FocuserStatus(BaseModel):
    state: DeviceState
    position: int | None = None
    is_moving: bool = False
    temperature: float | None = None


# --- Filter Wheel ---

class FilterWheelStatus(BaseModel):
    state: DeviceState
    current_slot: int | None = None   # 1-indexed
    filter_count: int | None = None
    filter_names: list[str] = []
    is_moving: bool = False


# --- Rotator ---

class RotatorStatus(BaseModel):
    state: DeviceState
    position: float | None = None    # degrees
    is_moving: bool = False
