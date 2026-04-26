from datetime import datetime, timezone
from typing import Literal
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
    gain: int | None
    binning: int


class ExposureCompleted(BaseEvent):
    type: Literal["imager.exposure_completed"] = "imager.exposure_completed"
    device_id: str
    fits_path: str
    preview_path: str
    preview_path_linear: str | None = None
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
    ra: float   # ICRS degrees
    dec: float  # ICRS degrees


class MountSlewCompleted(BaseEvent):
    type: Literal["mount.slew_completed"] = "mount.slew_completed"
    device_id: str
    ra: float   # ICRS degrees
    dec: float  # ICRS degrees


class MountSlewAborted(BaseEvent):
    type: Literal["mount.slew_aborted"] = "mount.slew_aborted"
    device_id: str


class MountTargetSet(BaseEvent):
    type: Literal["mount.target_set"] = "mount.target_set"
    device_id: str
    ra: float            # ICRS degrees
    dec: float           # ICRS degrees
    name: str | None = None
    source: str | None = None


class MountParked(BaseEvent):
    type: Literal["mount.parked"] = "mount.parked"
    device_id: str


class MountSynced(BaseEvent):
    type: Literal["mount.synced"] = "mount.synced"
    device_id: str
    ra: float   # ICRS degrees
    dec: float  # ICRS degrees


class MountTrackingChanged(BaseEvent):
    type: Literal["mount.tracking_changed"] = "mount.tracking_changed"
    device_id: str
    tracking: bool
    mode: str | None = None


class MountUnparked(BaseEvent):
    type: Literal["mount.unparked"] = "mount.unparked"
    device_id: str


class MountOperationFailed(BaseEvent):
    type: Literal["mount.operation_failed"] = "mount.operation_failed"
    device_id: str
    operation: str  # "slew" | "park" | "meridian_flip"
    reason: str


class MountMeridianFlipStarted(BaseEvent):
    type: Literal["mount.meridian_flip_started"] = "mount.meridian_flip_started"
    device_id: str


class MountMeridianFlipCompleted(BaseEvent):
    type: Literal["mount.meridian_flip_completed"] = "mount.meridian_flip_completed"
    device_id: str


# --- Focuser events ---

class FocuserMoveStarted(BaseEvent):
    type: Literal["focuser.move_started"] = "focuser.move_started"
    device_id: str
    target_position: int


class FocuserMoveCompleted(BaseEvent):
    type: Literal["focuser.move_completed"] = "focuser.move_completed"
    device_id: str
    position: int


class FocuserHalted(BaseEvent):
    type: Literal["focuser.halted"] = "focuser.halted"
    device_id: str
    position: int | None = None


class FocuserPositionUpdated(BaseEvent):
    """High-frequency event: fired on every ABS_FOCUS_POSITION update from the driver.
    Not written to the event log — used only for real-time UI state updates."""
    type: Literal["focuser.position_updated"] = "focuser.position_updated"
    device_id: str
    position: int


class MountCoordsUpdated(BaseEvent):
    """High-frequency event: fired at most 1 Hz when EQUATORIAL_EOD_COORD changes.
    Not written to the event log — used for real-time RA/Dec in the UI and plugins
    (e.g. Stellarium sync)."""
    type: Literal["mount.coords_updated"] = "mount.coords_updated"
    device_id: str
    ra: float | None       # ICRS J2000 decimal hours
    dec: float | None      # ICRS J2000 decimal degrees
    ra_jnow: float | None  # JNow decimal hours (raw driver value)
    dec_jnow: float | None # JNow decimal degrees (raw driver value)


# --- Filter Wheel events ---

class FilterWheelFilterChanged(BaseEvent):
    type: Literal["filter_wheel.filter_changed"] = "filter_wheel.filter_changed"
    device_id: str
    slot: int
    filter_name: str | None = None


