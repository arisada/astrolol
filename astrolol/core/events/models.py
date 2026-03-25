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

class LogLevel(str):
    pass


class LogEvent(BaseEvent):
    type: Literal["log"] = "log"
    level: str  # "debug" | "info" | "warning" | "error"
    component: str
    message: str


# Discriminated union — add new event types here as they are introduced
Event = Annotated[
    Union[DeviceConnected, DeviceDisconnected, DeviceStateChanged, LogEvent],
    Field(discriminator="type"),
]
