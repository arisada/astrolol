"""Python-level access to the object resolver, for other components (e.g. the sequencer).

Registered as ``app.state.object_resolver``. Consumers call it duck-typed; the REST
search route uses the same ``search_objects`` function, so both behave identically.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from astrolol.plugins.object_resolver import simbad, solar_system
from astrolol.plugins.object_resolver.catalog import ObjectCatalog
from astrolol.plugins.object_resolver.settings import ObjectResolverSettings


class ObjectMatch(BaseModel):
    name: str
    aliases: list[str]
    ra: float
    dec: float
    type: str
    source: str
    distance_arcmin: float | None = None
    mag: float | None = None
    size_arcmin: float | None = None   # major axis


async def search_objects(
    catalog: ObjectCatalog,
    settings: ObjectResolverSettings,
    q: str,
    limit: int = 20,
    when: datetime | None = None,
    site: solar_system.Site | None = None,
    groups: Collection[str] | None = None,
) -> list[ObjectMatch]:
    """Catalog + solar-system search, with the optional SIMBAD fallback when nothing matched.

    Solar-system positions are topocentric when *site* is given. *groups* (see TYPE_GROUPS)
    keeps only those kinds of object; the SIMBAD fallback, whose types are unknown, is then off."""
    results: list[dict[str, Any]] = catalog.search(q, limit=limit, groups=groups)
    for r in results:
        r.setdefault("source", "catalog")
    if groups is None or "solar_system" in groups:
        results.extend(solar_system.search(q, when=when, site=site))
    if not results and groups is None and settings.simbad_fallback:
        hit = await simbad.resolve(q)
        if hit:
            results.append(hit)
    return [ObjectMatch(**r) for r in results[:limit]]


def _norm(name: str) -> str:
    return "".join(name.lower().split())


def active_site(app: Any) -> solar_system.Site | None:
    """(lat, lon, altitude) of the Site in the active profile, if there is one."""
    from astrolol.equipment.optical_path import find_profile_site

    profile = getattr(app.state, "active_profile", None)
    equipment = getattr(app.state, "equipment_store", None)
    if profile is None or equipment is None:
        return None
    site = find_profile_site(profile, equipment)
    return None if site is None else (site.latitude, site.longitude, site.altitude)


class ObjectResolverService:
    """Reads the catalog and settings from ``app.state`` on each call (they can change)."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def search(
        self, q: str, limit: int = 20, when: datetime | None = None
    ) -> list[ObjectMatch]:
        state = self._app.state
        return await search_objects(
            state.object_resolver_catalog, state.object_resolver_settings, q, limit, when,
            site=active_site(self._app),
        )

    def notable(
        self,
        groups: Collection[str] | None = None,
        when: datetime | None = None,
        site: solar_system.Site | None = None,
    ) -> list[ObjectMatch]:
        """The well-known objects of the given kinds (None: all) for observing lists, with the
        Moon and planets placed for *when* and *site*."""
        state = self._app.state
        results: list[dict[str, Any]] = state.object_resolver_catalog.notable(groups)
        for r in results:
            r.setdefault("source", "catalog")
        if groups is None or "solar_system" in groups:
            results.extend(solar_system.bodies(when=when, site=site))
        return [ObjectMatch(**r) for r in results]

    async def lookup(self, name: str, when: datetime | None = None) -> ObjectMatch | None:
        """The object whose name or alias is exactly *name* (ignoring case and spaces).

        A fuzzy best guess could silently be the wrong object, so there is none: no exact
        match returns None.
        """
        wanted = _norm(name)
        for match in await self.search(name, limit=50, when=when):
            if _norm(match.name) == wanted or any(_norm(a) == wanted for a in match.aliases):
                return match
        return None
