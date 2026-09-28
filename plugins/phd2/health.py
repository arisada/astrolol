"""Guiding health: is guiding healthy right now, and how good was it over a time window.

Fed by the PHD2 client's event handler; kept separate (with an injectable clock) so it can
be tested without PHD2. A consumer takes ``mark()`` before an exposure and asks
``stats(mark)`` after it to learn the guiding RMS and how long the frame was unguided.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from plugins.phd2.models import GuidingHealth, GuidingStats

_MAX_STEPS = 20_000  # ~11 h at one step every 2 s
_MAX_GAPS = 2_000


@dataclass
class _Gap:
    start: float
    end: float | None
    reason: str
    was_guiding: bool  # the gap interrupted active guiding (a "loss")


class GuidingHealthTracker:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._steps: deque[tuple[float, float, float]] = deque(maxlen=_MAX_STEPS)
        self._gaps: deque[_Gap] = deque(maxlen=_MAX_GAPS)
        self._open: _Gap | None = _Gap(
            start=clock(), end=None, reason="not_guiding", was_guiding=False
        )
        self._gaps.append(self._open)
        self._guiding_since: float | None = None

    # ── Inputs ───────────────────────────────────────────────────────────

    def on_step(self, ra_arcsec: float, dec_arcsec: float) -> None:
        """A guide step was received: the star is being tracked."""
        now = self._clock()
        self._steps.append((now, ra_arcsec, dec_arcsec))
        if self._open is not None:
            self._open.end = now
            self._open = None
            self._guiding_since = now

    def on_lost(self, reason: str) -> None:
        """Guiding stopped or the star was lost. Idempotent while already unguided."""
        if self._open is not None:
            return
        gap = _Gap(start=self._clock(), end=None, reason=reason, was_guiding=True)
        self._gaps.append(gap)
        self._open = gap
        self._guiding_since = None

    # ── Queries ──────────────────────────────────────────────────────────

    def mark(self) -> float:
        return self._clock()

    def health(self) -> GuidingHealth:
        now = self._clock()
        if self._open is None:
            assert self._guiding_since is not None
            return GuidingHealth(guiding=True, guiding_for_s=round(now - self._guiding_since, 1))
        return GuidingHealth(
            guiding=False,
            unguided_for_s=round(now - self._open.start, 1),
            reason=self._open.reason,
        )

    def stats(self, since: float, until: float | None = None) -> GuidingStats:
        until = self._clock() if until is None else until
        ra = [s[1] for s in self._steps if since <= s[0] <= until]
        dec = [s[2] for s in self._steps if since <= s[0] <= until]
        unguided = 0.0
        losses = 0
        for gap in self._gaps:
            end = until if gap.end is None else gap.end
            overlap = min(end, until) - max(gap.start, since)
            if overlap > 0:
                unguided += overlap
            if gap.was_guiding and since <= gap.start <= until:
                losses += 1
        rms_ra = _rms(ra)
        rms_dec = _rms(dec)
        return GuidingStats(
            duration_s=round(until - since, 2),
            steps=len(ra),
            rms_ra=rms_ra,
            rms_dec=rms_dec,
            rms_total=(
                round(math.hypot(rms_ra, rms_dec), 3)
                if rms_ra is not None and rms_dec is not None
                else None
            ),
            unguided_s=round(unguided, 1),
            losses=losses,
        )


def _rms(values: list[float]) -> float | None:
    if not values:
        return None
    return round(math.sqrt(sum(v * v for v in values) / len(values)), 3)
