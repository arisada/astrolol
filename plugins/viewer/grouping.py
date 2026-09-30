"""Grouping rules: what counts as "the same session" for each frame type, and the
noon-to-noon night bucket frames are grouped within.

Astrophotography sessions are repetitive by design (the same target/filter/settings
shot dozens to hundreds of times a night), so the viewer's default browse view groups
frames instead of listing them all flat. What "same session" means differs by frame
type — see the table in VIEWER_SPECS.md for the reasoning behind each rule below.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta


def round_exposure(exposure_s: float | None) -> float | None:
    """Round to the millisecond so float drift between frames doesn't split a group."""
    if exposure_s is None:
        return None
    return round(float(exposure_s), 3)


def round_gain(gain: float | None) -> int | None:
    if gain is None:
        return None
    return int(round(float(gain)))


def normalize_filter_name(name: str | None) -> str:
    return (name or "").strip()


def compute_night(captured_at: datetime, sitelong_deg: float | None) -> str:
    """Noon-to-noon local-day bucket, as an ISO date string.

    Local time is estimated from ``SITELONG`` (15 degrees of longitude per hour of
    solar-time offset from UTC) when the header recorded it; otherwise this falls back
    to the server's own configured timezone. Neither is a rigorous per-site timezone
    lookup — a genuinely correct implementation would need a timezone/IANA-zone
    database keyed by lat/long, which is more machinery than a grouping heuristic
    warrants. This is a deliberate, documented simplification.
    """
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=None)
        utc = captured_at
    else:
        utc = captured_at
    if sitelong_deg is not None:
        local = utc + timedelta(hours=sitelong_deg / 15.0)
    else:
        local = utc.astimezone() if utc.tzinfo is not None else utc
    bucket = local - timedelta(hours=12)
    return bucket.date().isoformat()


def sky_cell(ra_deg: float, dec_deg: float) -> tuple[float, float]:
    """A ~1-degree sky cell, used only as a grouping fallback for blank object names.

    Without this, two different untracked pointings shot the same night at the same
    settings would otherwise collapse into a single group — exactly the case the
    "set as target" feature exists to help with.
    """
    cell_dec = round(dec_deg)
    cell_ra = round(ra_deg * math.cos(math.radians(dec_deg)))
    return float(cell_dec), float(cell_ra)


def compute_group_key(
    *,
    frame_type: str,
    object_name: str,
    filter_name: str,
    camera_name: str,
    exposure_s: float | None,
    binning: int | None,
    gain: int | None,
    night: str,
    sky_cell_ra: float | None,
    sky_cell_dec: float | None,
) -> str:
    """The internal grouping key. Never exposed via the API — see GroupSummary /
    the /images filter params, which use the plain field values instead."""
    ft = frame_type or "unknown"
    if ft == "flat":
        # Auto-exposure sky flats vary exposure frame to frame; grouping on it would
        # give one group per frame instead of one group per flat set.
        parts = [ft, filter_name, camera_name, binning, gain, night]
    elif ft == "bias":
        # Exposure is dropped (nominally fixed/minimum anyway); gain is KEPT — bias
        # frames at different gains are not the same calibration set.
        parts = [ft, camera_name, binning, gain, night]
    elif ft == "dark":
        # Dark libraries are captured once and reused across months — bucketing by
        # night would fragment one dark library into dozens of one-off groups.
        parts = [ft, camera_name, exposure_s, binning, gain]
    else:  # light, unknown
        obj_key = object_name if object_name else f"cell:{sky_cell_ra}:{sky_cell_dec}"
        parts = [ft, obj_key, filter_name, camera_name, exposure_s, binning, gain, night]
    return "|".join("" if p is None else str(p) for p in parts)
