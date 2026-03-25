from datetime import datetime, timezone
from typing import Literal, Annotated, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from astrolol.devices.base.models import DeviceState


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid4())


class BaseEvent(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)


# --- Device events ---

class DeviceConnected(BaseEvent):
    type: Literal["device.connected"] = "device.connected"
    device_kind: str
    device_key: str


class DeviceDisconnected(BaseEvent):
    type: Literal["device.disconnected"] = "device.disconnected"
    device_kind: str
    device_key: str
    reason: str | None = None


class DeviceStateChanged(BaseEvent):
    type: Literal["device.state_changed"] = "device.state_changed"
    device_kind: str
    device_key: str
    old_state: DeviceState
    new_state: DeviceState


# --- Log event (for live log streaming to clients) ---

class LogEvent(BaseEvent):
    type: Literal["log"] = "log"
    level: str  # "debug" | "info" | "warning" | "error"
    component: str
    message: str


# --- Imager events ---

class ExposureStarted(BaseEvent):
    type: Literal["imager.exposure_started"] = "imager.exposure_started"
    device_id: str
    duration: float
    gain: int
    binning: int


class ExposureCompleted(BaseEvent):
    type: Literal["imager.exposure_completed"] = "imager.exposure_completed"
    device_id: str
    fits_path: str
    preview_path: str
    duration: float
    width: int
    height: int


class ExposureFailed(BaseEvent):
    type: Literal["imager.exposure_failed"] = "imager.exposure_failed"
    device_id: str
    reason: str


class LoopStarted(BaseEvent):
    type: Literal["imager.loop_started"] = "imager.loop_started"
    device_id: str


class LoopStopped(BaseEvent):
    type: Literal["imager.loop_stopped"] = "imager.loop_stopped"
    device_id: str


# --- Mount events ---

class MountSlewStarted(BaseEvent):
    type: Literal["mount.slew_started"] = "mount.slew_started"
    device_id: str
    ra: float
    dec: float


class MountSlewCompleted(BaseEvent):
    type: Literal["mount.slew_completed"] = "mount.slew_completed"
    device_id: str
    ra: float
    dec: float


class MountSlewAborted(BaseEvent):
    type: Literal["mount.slew_aborted"] = "mount.slew_aborted"
    device_id: str


class MountParked(BaseEvent):
    type: Literal["mount.parked"] = "mount.parked"
    device_id: str


class MountSynced(BaseEvent):
    type: Literal["mount.synced"] = "mount.synced"
    device_id: str
    ra: float
    dec: float


class MountTrackingChanged(BaseEvent):
    type: Literal["mount.tracking_changed"] = "mount.tracking_changed"
    device_id: str
    tracking: bool


# Discriminated union — add new event types here as they are introduced
Event = Annotated[
    Union[
        DeviceConnected, DeviceDisconnected, DeviceStateChanged, LogEvent,
        ExposureStarted, ExposureCompleted, ExposureFailed, LoopStarted, LoopStopped,
        MountSlewStarted, MountSlewCompleted, MountSlewAborted,
        MountParked, MountSynced, MountTrackingChanged,
    ],
    Field(discriminator="type"),
]
