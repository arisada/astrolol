"""Guider-independent guiding events."""

from __future__ import annotations

from typing import Literal

from astrolol.core.events.models import BaseEvent


class GuidingStateChanged(BaseEvent):
    """Guiding became active (steps arriving) or stopped / lost the star."""

    type: Literal["guiding.state_changed"] = "guiding.state_changed"
    guider: str
    guiding: bool
    reason: str | None = None  # why guiding stopped: star_lost, stopped, disconnected, …


class GuidingSettled(BaseEvent):
    type: Literal["guiding.settled"] = "guiding.settled"
    guider: str
    after: Literal["guide", "dither"]
    error: str | None = None  # None = settled
