"""Guiding interface: the Guider protocol, public models, events and errors."""

from astrolol.core.guiding.errors import GuiderBusy, GuiderError, GuiderNotConnected, SettleFailed
from astrolol.core.guiding.models import GuiderStatus, GuidingHealth, GuidingStats, SettleParams
from astrolol.core.guiding.service import (
    GUIDER_PRIORITY,
    Guider,
    UnknownGuider,
    active_guider_id,
    guiders,
    register_guider,
    require_active_guider,
    select_guider,
    unregister_guider,
)

__all__ = [
    "GUIDER_PRIORITY",
    "Guider",
    "GuiderBusy",
    "GuiderError",
    "GuiderNotConnected",
    "GuiderStatus",
    "GuidingHealth",
    "GuidingStats",
    "SettleFailed",
    "SettleParams",
    "UnknownGuider",
    "active_guider_id",
    "guiders",
    "register_guider",
    "require_active_guider",
    "select_guider",
    "unregister_guider",
]
