from enum import StrEnum
from pydantic import BaseModel, Field


class ImagerState(StrEnum):
    IDLE = "idle"
    EXPOSING = "exposing"
    LOOPING = "looping"
    ERROR = "error"


class DitherConfig(BaseModel):
    every_frames: int | None = Field(
        default=None, ge=1,
        description="Dither every N frames. None = never.",
    )
    every_minutes: float | None = Field(
        default=None, gt=0,
        description="Dither if at least N minutes have elapsed since last dither. None = never.",
    )
    pixels: float = Field(default=5.0, gt=0, description="Dither amount in guide camera pixels")
    ra_only: bool = Field(default=False, description="Dither in RA direction only")
    settle_pixels: float = Field(default=1.5, gt=0, description="Settle threshold in pixels")
    settle_time: int = Field(default=10, ge=0, description="Settle stability time in seconds")
    settle_timeout: int = Field(default=60, ge=1, description="Maximum settle wait in seconds")


class ExposureRequest(BaseModel):
    duration: float = Field(gt=0, description="Exposure duration in seconds")
    gain: int | None = Field(default=None, ge=0, description="None = leave driver gain unchanged")
    binning: int = Field(default=1, ge=1, le=4)
    frame_type: str = Field(default="light", description="light | dark | flat | bias")
    count: int | None = Field(
        default=None,
        ge=1,
        description="Number of exposures for a loop. Omit (or null) for infinite loop.",
    )
    save: bool = Field(default=True, description="Write to save directory; false = preview only")
    dither: DitherConfig | None = Field(
        default=None,
        description="Dither configuration for loop mode. Ignored for single exposures.",
    )


class ExposureResult(BaseModel):
    device_id: str
    fits_path: str
    preview_path: str
    preview_path_linear: str | None = None
    duration: float
    width: int
    height: int


class ImagerStatus(BaseModel):
    device_id: str
    state: ImagerState


class ImagerDeviceSettings(BaseModel):
    """Per-camera imager settings persisted server-side."""
    duration: float = Field(default=5.0, gt=0)
    binning: int = Field(default=1, ge=1, le=4)
    frame_type: str = Field(default="light")
    save_subs: bool = True
    dither_frames: str = ""
    dither_minutes: str = ""
    histo_auto: bool = True
    target_temp: str = ""
