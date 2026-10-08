"""Pulse guiding: short timed moves of the mount, used by autoguiders."""

from __future__ import annotations

from typing import Literal

PulseDirection = Literal["N", "S", "E", "W"]


class PulseGuideNotSupported(Exception):
    """The device has no pulse-guide output (no ST4 port, or the driver doesn't offer one)."""
