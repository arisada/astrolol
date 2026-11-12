"""Events published by the stacked camera."""
from __future__ import annotations

from typing import ClassVar, Literal

from astrolol.core.events.models import BaseEvent


class StackProgress(BaseEvent):
    """Where a long exposure stands. A restatement of the current state: only the latest is kept."""

    snapshot: ClassVar[bool] = True

    type: Literal["stacked_camera.progress"] = "stacked_camera.progress"
    device_id: str
    active: bool  # False once the exposure is over, however it ended
    subs_done: int = 0
    subs_total: int = 0
    exposure_done: float = 0.0  # seconds of light in the stack so far
    exposure_total: float = 0.0
