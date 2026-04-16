from enum import StrEnum
from pydantic import BaseModel, Field


class ImagerState(StrEnum):
    IDLE = "idle"
    EXPOSING = "exposing"
    LOOPING = "looping"
    ERROR = "error"


class ExposureRequest(BaseModel):
    duration: float = Field(gt=0, description="Exposure duration in seconds")
    gain: int = Field(default=0, ge=0)
    binning: int = Field(default=1, ge=1, le=4)
    frame_type: str = Field(default="light", description="light | dark | flat | bias")
    count: int | None = Field(
        default=None,
        ge=1,
        description="Number of exposures for a loop. Omit (or null) for infinite loop.",
    )
    save: bool = Field(default=True, description="Write to save directory; false = preview only")


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
