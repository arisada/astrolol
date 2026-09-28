"""Resolve a TargetRef to coordinates at execution time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from astrolol.core.sequencer.models import TargetRef

logger = structlog.get_logger()


class TargetUnresolvable(Exception):
    pass


@dataclass
class ResolvedTarget:
    ra: float | None  # ICRS degrees; None for kind=current
    dec: float | None
    name: str
    source: str  # favorite | catalog | coordinates | current | snapshot
    warning: str | None = None


def _snapshot(ref: TargetRef, why: str) -> ResolvedTarget:
    if ref.ra is None or ref.dec is None:
        raise TargetUnresolvable(f"{why}, and the task has no saved coordinates for '{ref.name}'")
    return ResolvedTarget(
        ra=ref.ra,
        dec=ref.dec,
        name=ref.name,
        source="snapshot",
        warning=f"{why}; using the coordinates saved with the task",
    )


async def resolve_target(ref: TargetRef, app: Any, when: datetime | None = None) -> ResolvedTarget:
    """Resolve *ref*. Uses the target plugin's favorites and the object_resolver plugin
    through their ``app.state`` services (duck-typed; either may be disabled), falling
    back to the snapshot coordinates saved in the TargetRef."""
    if ref.kind == "current":
        return ResolvedTarget(ra=None, dec=None, name=ref.name, source="current")

    if ref.kind == "coordinates":
        assert ref.ra is not None and ref.dec is not None
        return ResolvedTarget(ra=ref.ra, dec=ref.dec, name=ref.name, source="coordinates")

    if ref.kind == "favorite":
        favorites = getattr(app.state, "target_favorites", None)
        if favorites is None:
            return _snapshot(ref, "The target plugin is not enabled")
        fav = favorites.get(ref.favorite_id)
        if fav is None:
            return _snapshot(ref, f"Favorite '{ref.name}' no longer exists")
        return ResolvedTarget(ra=fav.ra, dec=fav.dec, name=ref.name, source="favorite")

    # kind == "catalog"
    resolver = getattr(app.state, "object_resolver", None)
    if resolver is None:
        return _snapshot(ref, "The object_resolver plugin is not enabled")
    try:
        hit = await resolver.lookup(ref.catalog_id, when=when or datetime.now(UTC))
    except Exception as exc:
        logger.warning("sequencer.target_lookup_failed", name=ref.catalog_id, error=str(exc))
        return _snapshot(ref, f"Looking up '{ref.catalog_id}' failed ({exc})")
    if hit is None:
        return _snapshot(ref, f"'{ref.catalog_id}' was not found by the object resolver")
    return ResolvedTarget(ra=hit.ra, dec=hit.dec, name=ref.name, source="catalog")
