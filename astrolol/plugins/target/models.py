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
    aliases: list[str] = []         # Names in other catalogues (e.g. ["NGC 224", "Andromeda Galaxy"])
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
    # Calendar date of the evening (dusk side) of the observation night, "YYYY-MM-DD"
    obs_date: str = ""

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
    moon_altitude_curve: list[AltitudePoint] = []

    # Set when profile has no observer location configured
    observer_location_missing: bool = False


# ── Tonight ───────────────────────────────────────────────────────────────────

class TonightItem(BaseModel):
    """One suggested object, with how it is placed during the coming dark hours."""
    name: str
    aliases: list[str] = []
    type: str = ""
    ra: float                           # ICRS degrees
    dec: float
    source: str = "catalog"
    mag: float | None = None
    size_arcmin: float | None = None    # major axis
    alt_now: float                      # degrees at the start of the window (now, or dusk)
    peak_alt: float
    peak_time: str                      # UTC ISO
    rise_time: str | None = None        # when it first gets above the minimum altitude, if not yet
    set_time: str | None = None         # when it drops below it again, if before the window ends
    moon_separation: float | None = None
    near_moon: bool = False             # too close to a bright Moon that is up


class TonightResult(BaseModel):
    observer_location_missing: bool = False
    no_darkness: bool = False           # the Sun does not go far enough below the horizon
    window_start: str | None = None     # UTC ISO: now, or dusk when it is still daylight
    window_end: str | None = None
    min_altitude_deg: float = 30.0
    moon_illumination: float | None = None
    items: list[TonightItem] = []
