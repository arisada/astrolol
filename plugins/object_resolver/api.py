"""Object resolver REST API."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel

from plugins.object_resolver import simbad, solar_system
from plugins.object_resolver.catalog import ObjectCatalog

router = APIRouter(prefix="/plugins/object_resolver", tags=["object_resolver"])


class ObjectMatch(BaseModel):
    name: str
    aliases: list[str]
    ra: float
    dec: float
    type: str
    source: str
    distance_arcmin: float | None = None


class CatalogStatus(BaseModel):
    ready: bool
    object_count: int
    last_updated: str | None
    syncing: bool


def _catalog(request: Request) -> ObjectCatalog:
    return request.app.state.object_resolver_catalog  # type: ignore[no-any-return]


def _parse_when(when: str | None) -> datetime | None:
    if when is None:
        return None
    try:
        return datetime.fromisoformat(when).astimezone(timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid 'when'; use ISO 8601.")


@router.get("/status")
async def status(request: Request) -> CatalogStatus:
    cat = _catalog(request)
    return CatalogStatus(
        ready=cat.is_populated(),
        object_count=cat.object_count(),
        last_updated=cat.last_updated(),
        syncing=request.app.state.object_resolver_syncing,
    )


@router.post("/sync", status_code=202)
async def sync(request: Request, background_tasks: BackgroundTasks) -> dict:
    if request.app.state.object_resolver_syncing:
        raise HTTPException(status_code=409, detail="Sync already in progress.")
    request.app.state.object_resolver_syncing = True

    async def _run() -> None:
        try:
            await _catalog(request).sync()
        finally:
            request.app.state.object_resolver_syncing = False

    background_tasks.add_task(_run)
    return {"status": "accepted"}


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    when: str | None = Query(None),
) -> list[ObjectMatch]:
    t = _parse_when(when)
    settings = request.app.state.object_resolver_settings

    results: list[dict] = _catalog(request).search(q, limit=limit)
    for r in results:
        r.setdefault("source", "catalog")

    results.extend(solar_system.search(q, when=t))

    if not results and settings.simbad_fallback:
        hit = await simbad.resolve(q)
        if hit:
            results.append(hit)

    return [ObjectMatch(**r) for r in results[:limit]]


@router.get("/resolve")
async def resolve(
    request: Request,
    ra: float = Query(..., ge=0.0, lt=360.0),
    dec: float = Query(..., ge=-90.0, le=90.0),
    radius: float = Query(
        30.0, gt=0.0, le=600.0, description="Search radius in arcminutes"
    ),
    when: str | None = Query(None),
) -> list[ObjectMatch]:
    t = _parse_when(when)

    results: list[dict] = _catalog(request).cone_search(ra, dec, radius)
    for r in results:
        r.setdefault("source", "catalog")

    results.extend(solar_system.cone_search(ra, dec, radius, when=t))
    results.sort(key=lambda x: x.get("distance_arcmin") or 0.0)

    return [ObjectMatch(**r) for r in results]
