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


# --- Filter Wheel events ---

class FilterWheelFilterChanged(BaseEvent):
    type: Literal["filter_wheel.filter_changed"] = "filter_wheel.filter_changed"
    device_id: str
    slot: int
    filter_name: str | None = None


# --- PHD2 events ---

class Phd2Connected(BaseEvent):
    type: Literal["phd2.connected"] = "phd2.connected"


class Phd2Disconnected(BaseEvent):
    type: Literal["phd2.disconnected"] = "phd2.disconnected"


class Phd2StateChanged(BaseEvent):
    type: Literal["phd2.state_changed"] = "phd2.state_changed"
    state: str  # PHD2 AppState: Stopped, Guiding, Calibrating, Paused, etc.


class Phd2GuideStep(BaseEvent):
    type: Literal["phd2.guide_step"] = "phd2.guide_step"
    frame: int
    ra_dist: float    # arcsec (pixels × pixel_scale; raw pixels if scale unknown)
    dec_dist: float
    ra_corr: float    # guide pulse duration, ms
    dec_corr: float
    star_snr: float | None = None


class Phd2Settled(BaseEvent):
    type: Literal["phd2.settled"] = "phd2.settled"
    error: str | None = None  # None = success


# --- Plate-solve events ---

class PlatesolveStarted(BaseEvent):
    type: Literal["platesolve.started"] = "platesolve.started"
    solve_id: str
    fits_path: str


class PlatesolveCompleted(BaseEvent):
    type: Literal["platesolve.completed"] = "platesolve.completed"
    solve_id: str
    ra: float           # degrees J2000
    dec: float          # degrees J2000
    rotation: float     # degrees, North through East
    pixel_scale: float  # arcsec/pixel
    field_w: float      # degrees
    field_h: float      # degrees
    duration_ms: int


class PlatesolveFailed(BaseEvent):
    type: Literal["platesolve.failed"] = "platesolve.failed"
    solve_id: str
    reason: str


class PlatesolveCancelled(BaseEvent):
    type: Literal["platesolve.cancelled"] = "platesolve.cancelled"
    solve_id: str


# Discriminated union — add new event types here as they are introduced
Event = Annotated[
    Union[
        DeviceConnected, DeviceDisconnected, DeviceStateChanged, LogEvent,
        ExposureStarted, ExposureCompleted, ExposureFailed, LoopStarted, LoopStopped,
        MountSlewStarted, MountSlewCompleted, MountSlewAborted,
        MountParked, MountUnparked, MountSynced, MountTrackingChanged, MountOperationFailed,
        MountMeridianFlipStarted, MountMeridianFlipCompleted, MountTargetSet,
        FocuserMoveStarted, FocuserMoveCompleted, FocuserHalted,
        FilterWheelFilterChanged,
        Phd2Connected, Phd2Disconnected, Phd2StateChanged, Phd2GuideStep, Phd2Settled,
        PlatesolveStarted, PlatesolveCompleted, PlatesolveFailed, PlatesolveCancelled,
    ],
    Field(discriminator="type"),
]
