"""Pydantic models for the target plugin."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Favorites ─────────────────────────────────────────────────────────────────

class FavoriteTarget(BaseModel):
    id: str = Field(default_factory=_uid)
    name: str                       # User-defined label
    ra: float                       # ICRS degrees
    dec: float                      # ICRS degrees
    object_name: str = ""           # Canonical name from catalogue (e.g. "M 42")
    object_type: str = ""           # Human label (e.g. "Emission Nebula")
    notes: str = ""
    added_at: datetime = Field(default_factory=_now)


# ── Plugin settings (persisted in plugin_settings['target']) ──────────────────

class TargetSettings(BaseModel):
    favorites: list[FavoriteTarget] = []
    min_altitude_deg: float = Field(default=30.0, ge=0.0, le=90.0)


# ── Ephemeris ─────────────────────────────────────────────────────────────────

class AltitudePoint(BaseModel):
    """Altitude at a single moment in time (local wall-clock ISO string)."""
    time: str       # ISO 8601 UTC
    alt: float      # degrees above horizon


class TwilightTimes(BaseModel):
    """Twilight boundary times (UTC ISO strings).  None = sun never crosses that boundary."""
    astronomical_dusk: str | None = None
    nautical_dusk: str | None = None
    civil_dusk: str | None = None
    civil_dawn: str | None = None
    nautical_dawn: str | None = None
    astronomical_dawn: str | None = None


class EphemerisResult(BaseModel):
    # Rise / transit / set (UTC ISO strings, None = circumpolar or never rises)
    rise: str | None = None
    transit: str | None = None
    set: str | None = None
    circumpolar: bool = False
    never_rises: bool = False

    # Altitude at transit
    peak_alt: float | None = None       # degrees
    peak_time: str | None = None        # UTC ISO string

    # Imaging window: first contiguous block where alt > min_altitude_deg AND dark (UTC ISO strings)
    imaging_window_start: str | None = None
    imaging_window_end: str | None = None
    # True when the object never exceeds min_altitude_deg during darkness (even if it does so in daytime)
    not_observable_at_night: bool = False

    # Altitude curve (one point per 10 minutes over the 24 h window)
    altitude_curve: list[AltitudePoint] = []

    # Twilight
    twilight: TwilightTimes = Field(default_factory=TwilightTimes)

    # Moon
    moon_separation: float | None = None    # degrees
    moon_illumination: float | None = None  # 0.0 – 1.0

    # Set when profile has no observer location configured
    observer_location_missing: bool = False
