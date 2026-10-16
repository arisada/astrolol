"""Nudge speeds, in multiples of the sidereal rate.

A rate is either one of the INDI-style names or "<n>x" (e.g. "16x", "800x"), which is also what
the INDI EQMod driver calls its slew rates, so the UI can offer the same list for both.
"""
from __future__ import annotations

import re

# 800x is the fastest the Sky-Watcher controllers are driven at by EQMOD.
MAX_NUDGE_X_SIDEREAL = 800.0
NUDGE_ALIASES_X_SIDEREAL = {"guide": 0.5, "centering": 16.0, "find": 64.0, "max": MAX_NUDGE_X_SIDEREAL}

_MULTIPLIER = re.compile(r"^(\d+(?:\.\d+)?)x$", re.IGNORECASE)


def nudge_speed_x_sidereal(rate: str) -> float:
    """Speed for a rate name or "<n>x"; ValueError if it is neither or outside 0..800x."""
    if rate in NUDGE_ALIASES_X_SIDEREAL:
        return NUDGE_ALIASES_X_SIDEREAL[rate]
    match = _MULTIPLIER.match(rate.strip())
    if match is None:
        raise ValueError(f"Unknown nudge rate {rate!r}: use a speed such as '16x' or one of "
                         f"{', '.join(NUDGE_ALIASES_X_SIDEREAL)}")
    speed = float(match.group(1))
    if not 0 < speed <= MAX_NUDGE_X_SIDEREAL:
        raise ValueError(f"Nudge speed must be above 0 and at most {MAX_NUDGE_X_SIDEREAL:g}x sidereal")
    return speed
