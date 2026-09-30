"""Viewer plugin — REST API. Everything, browsing and mutation alike, lives under this
one router (``/plugins/viewer/...``) — there is no separate "core" fetch API and no
group_key-based endpoint: a group is fully described by its field values, so expanding
one is just GET /images with those same values as filters (see index.py's grouping doc)."""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from astrolol.imaging.preview import fits_to_jpeg, fits_to_jpeg_linear
from astrolol.profiles.store import ProfileStore
from plugins.viewer.index import ImageFilters, RescanInProgress, ViewerIndex
from plugins.viewer.models import (
    Facets,
    GroupListResponse,
    ImageListResponse,
    ImageRecord,
    LibraryStatus,
    RejectedItem,
    RenderRequest,
    RollupRow,
    UnrejectRequest,
    ViewerRescanCompletedEvent,
    ViewerRescanProgressEvent,
    ViewerRescanStartedEvent,
    ViewerSettings,
)
from plugins.viewer.settings import default_library_dir
from plugins.viewer.thumbnails import ensure_thumbnail, gc as gc_thumbnails

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/viewer", tags=["viewer"])

_REJECTED_DIR_NAME = "_rejected"


def _index(request: Request) -> ViewerIndex:
    return request.app.state.viewer_index


def _cache_dir(request: Request) -> Path:
    return request.app.state.viewer_cache_dir


def _thumbs_dir(request: Request) -> Path:
    return request.app.state.viewer_thumbs_dir


def _profile_store(request: Request) -> ProfileStore:
    return request.app.state.profile_store


def resolve_library_dir(profile_store: ProfileStore | None) -> Path:
    if profile_store is None:
        return default_library_dir("~/astrolol_pictures/%D")
    user_settings = profile_store.get_user_settings()
    raw = user_settings.plugin_settings.get("viewer", {})
    viewer_settings = ViewerSettings(**raw)
    if viewer_settings.library_dir:
        return Path(viewer_settings.library_dir).expanduser()
    return default_library_dir(user_settings.save_dir_template)


def _library_dir(request: Request) -> Path:
    return resolve_library_dir(getattr(request.app.state, "profile_store", None))


# --- Settings ---

@router.get("/settings", response_model=ViewerSettings)
async def get_settings(request: Request) -> ViewerSettings:
    store = _profile_store(request)
    raw = store.get_user_settings().plugin_settings.get("viewer", {})
    settings = ViewerSettings(**raw)
    if not settings.library_dir:
        settings.library_dir = str(_library_dir(request))
    return settings


@router.put("/settings", response_model=ViewerSettings)
async def put_settings(body: ViewerSettings, request: Request) -> ViewerSettings:
    store = _profile_store(request)
    current = store.get_user_settings()
    new_ps = {**current.plugin_settings, "viewer": body.model_dump()}
    store.update_user_settings(current.model_copy(update={"plugin_settings": new_ps}))

    # Changing library_dir invalidates anything indexed from outside the new root.
    index = _index(request)
    new_dir = Path(body.library_dir).expanduser() if body.library_dir else _library_dir(request)
    await index.purge_outside(new_dir)
    live_ids = await index.all_ids()
    gc_thumbnails(_thumbs_dir(request), live_ids)
    gc_thumbnails(_cache_dir(request), live_ids)
    logger.info("viewer.library_dir_changed", library_dir=str(new_dir))
    return body


@router.get("/status", response_model=LibraryStatus)
async def status(request: Request) -> LibraryStatus:
    library_dir = _library_dir(request)
    index = _index(request)
    image_count = await index.count_under(library_dir)
    try:
        usage = shutil.disk_usage(library_dir if library_dir.exists() else library_dir.parent)
        total_bytes, free_bytes = usage.total, usage.free
    except OSError:
        total_bytes = free_bytes = 0
    rejected_count, rejected_bytes = _rejected_stats(library_dir)
    return LibraryStatus(
        library_dir=str(library_dir), total_bytes=total_bytes, free_bytes=free_bytes,
        image_count=image_count, rescanning=index.is_rescanning,
        rejected_count=rejected_count, rejected_bytes=rejected_bytes,
    )


# --- Rescan ---

@router.post("/rescan", status_code=202)
async def start_rescan(request: Request) -> dict:
    index = _index(request)
    library_dir = _library_dir(request)
    event_bus = getattr(request.app.state, "event_bus", None)

    def _on_progress(scanned: int) -> None:
        if event_bus is not None:
            asyncio.create_task(event_bus.publish(ViewerRescanProgressEvent(scanned=scanned)))

    try:
        task = index.start_rescan(library_dir, on_progress=_on_progress)
    except RescanInProgress:
        raise HTTPException(status_code=409, detail="A rescan is already running.")

    # start_rescan() already created the task that runs index.scan(); wrap it (rather
    # than awaiting it here) so this endpoint returns immediately and events still get
    # published once it finishes, without starting a second, competing scan.
    async def _publish_lifecycle() -> None:
        if event_bus is not None:
            await event_bus.publish(ViewerRescanStartedEvent(library_dir=str(library_dir)))
        try:
            result = await task
            if event_bus is not None:
                await event_bus.publish(ViewerRescanCompletedEvent(**result.model_dump()))
        except asyncio.CancelledError:
            if event_bus is not None:
                await event_bus.publish(ViewerRescanCompletedEvent(cancelled=True))
        except Exception as exc:
            logger.error("viewer.rescan_failed", error=str(exc), exc_info=True)
            if event_bus is not None:
                await event_bus.publish(ViewerRescanCompletedEvent(error=str(exc)))

    asyncio.create_task(_publish_lifecycle())
    return {"status": "scanning", "library_dir": str(library_dir)}


@router.delete("/rescan", status_code=204)
async def cancel_rescan(request: Request) -> None:
    index = _index(request)
    if not index.is_rescanning:
        raise HTTPException(status_code=409, detail="No rescan is running.")
    index.request_cancel()


# --- Facets / rollup ---

@router.get("/facets", response_model=Facets)
async def facets(request: Request) -> Facets:
    return await _index(request).facets()


@router.get("/rollup", response_model=list[RollupRow])
async def rollup(request: Request) -> list[RollupRow]:
    return await _index(request).rollup()


# --- Groups / images ---

def _parse_frame_types(frame_type: list[str] | None) -> list[str] | None:
    return frame_type or None


@router.get("/groups", response_model=GroupListResponse)
async def list_groups(
    request: Request,
    frame_type: list[str] | None = Query(default=None),
    object_name: str | None = None,
    filter_name: str | None = None,
    camera_name: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> GroupListResponse:
    filters = ImageFilters(
        frame_types=_parse_frame_types(frame_type), object_name=None,
        filter_name=filter_name, camera_name=camera_name,
        date_from=date_from, date_to=date_to, search=search or object_name,
    )
    items, total = await _index(request).list_groups(filters, page=page, page_size=page_size)
    return GroupListResponse(items=items, total=total)


@router.get("/images", response_model=ImageListResponse)
async def list_images(
    request: Request,
    frame_type: list[str] | None = Query(default=None),
    object_name: str | None = None,
    filter_name: str | None = None,
    camera_name: str | None = None,
    exposure_s: float | None = None,
    binning: int | None = None,
    gain: int | None = None,
    night: str | None = None,
    sky_cell_ra: float | None = None,
    sky_cell_dec: float | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    star_count_min: int | None = None,
    star_count_max: int | None = None,
    hfr_min: float | None = None,
    hfr_max: float | None = None,
    ra_deg: float | None = None,
    dec_deg: float | None = None,
    radius_deg: float | None = None,
    before_captured_at: str | None = None,
    before_id: str | None = None,
    ascending: bool = False,
    limit: int = 50,
) -> ImageListResponse:
    filters = ImageFilters(
        frame_types=_parse_frame_types(frame_type), object_name=object_name,
        filter_name=filter_name, camera_name=camera_name, exposure_s=exposure_s,
        binning=binning, gain=gain, night=night, sky_cell_ra=sky_cell_ra,
        sky_cell_dec=sky_cell_dec, date_from=date_from, date_to=date_to, search=search,
        star_count_min=star_count_min, star_count_max=star_count_max,
        hfr_min=hfr_min, hfr_max=hfr_max, ra_deg=ra_deg, dec_deg=dec_deg, radius_deg=radius_deg,
    )
    items, total = await _index(request).list_images(
        filters, before_captured_at=before_captured_at, before_id=before_id,
        limit=min(limit, 200), ascending=ascending,
    )
    next_cursor = None
    if len(items) == min(limit, 200) and items:
        last = items[-1]
        next_cursor = f"{last.captured_at.isoformat()}|{last.id}"
    return ImageListResponse(items=items, total=total, next_cursor=next_cursor)


@router.get("/images/{image_id}", response_model=ImageRecord)
async def get_image(image_id: str, request: Request) -> ImageRecord:
    record = await _index(request).get(image_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    return record


async def _require_record(request: Request, image_id: str) -> ImageRecord:
    record = await _index(request).get(image_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    if not Path(record.path).exists():
        raise HTTPException(status_code=404, detail="Image file is missing on disk.")
    return record


@router.get("/images/{image_id}/thumbnail")
async def get_thumbnail(image_id: str, request: Request) -> FileResponse:
    record = await _require_record(request, image_id)
    out = await ensure_thumbnail(
        _thumbs_dir(request), record.id, record.size_bytes, record.mtime, Path(record.path),
    )
    return FileResponse(out, media_type="image/jpeg")


@router.get("/images/{image_id}/stats")
async def get_stats(image_id: str, request: Request) -> dict:
    """The histogram itself doesn't depend on stretch settings (only the clip markers
    do), so it's computed once with fixed default percentiles and cached — regardless
    of what black/white the user later picks for the adjustable preview."""
    record = await _require_record(request, image_id)
    cache_dir = _cache_dir(request)
    cache_dir.mkdir(parents=True, exist_ok=True)
    stats_path = cache_dir / f"{record.id}_{int(record.mtime)}.stats.json"
    if stats_path.exists():
        import json
        return json.loads(stats_path.read_text())

    tmp_jpeg = cache_dir / f"{record.id}_{int(record.mtime)}.stats.jpg"
    stats = await asyncio.to_thread(fits_to_jpeg, Path(record.path), tmp_jpeg, 85, 50.0, 99.0)
    import json
    stats_path.write_text(json.dumps(stats))
    tmp_jpeg.unlink(missing_ok=True)
    return stats


@router.get("/images/{image_id}/preview.jpg")
async def get_preview(
    image_id: str, request: Request,
    mode: str = "auto", black_pct: float = 50.0, white_pct: float = 99.0, quality: int = 85,
) -> FileResponse:
    record = await _require_record(request, image_id)
    cache_dir = _cache_dir(request)
    cache_dir.mkdir(parents=True, exist_ok=True)
    render = RenderRequest(mode=mode, black_pct=black_pct, white_pct=white_pct, quality=quality)
    out = cache_dir / (
        f"{record.id}_{int(record.mtime)}_{render.mode}_{render.black_pct}_"
        f"{render.white_pct}_{render.quality}.jpg"
    )
    if not out.exists():
        if render.mode == "linear":
            await asyncio.to_thread(fits_to_jpeg_linear, Path(record.path), out, render.quality)
        else:
            await asyncio.to_thread(
                fits_to_jpeg, Path(record.path), out, render.quality, render.black_pct, render.white_pct,
            )
    return FileResponse(out, media_type="image/jpeg")


@router.get("/images/{image_id}/fits")
async def download_fits(image_id: str, request: Request) -> FileResponse:
    record = await _require_record(request, image_id)
    return FileResponse(record.path, media_type="application/fits", filename=Path(record.path).name)


# --- Reject / unreject ---

def _rejected_root(library_dir: Path) -> Path:
    return library_dir / _REJECTED_DIR_NAME


def _rejected_stats(library_dir: Path) -> tuple[int, int]:
    root = _rejected_root(library_dir)
    if not root.exists():
        return 0, 0
    count = 0
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            count += 1
            total += p.stat().st_size
    return count, total


@router.post("/images/{image_id}/reject", status_code=204)
async def reject_image(image_id: str, request: Request) -> None:
    record = await _require_record(request, image_id)
    library_dir = _library_dir(request)
    src = Path(record.path)
    try:
        relative = src.resolve().relative_to(library_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Image is not under the configured library directory.")
    dst = _rejected_root(library_dir) / relative
    dst.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.move, str(src), str(dst))
    await _index(request).remove_by_path(src)
    live_ids = await _index(request).all_ids()
    gc_thumbnails(_thumbs_dir(request), live_ids)
    logger.info("viewer.image_rejected", path=str(src), moved_to=str(dst))


@router.get("/rejected", response_model=list[RejectedItem])
async def list_rejected(request: Request) -> list[RejectedItem]:
    library_dir = _library_dir(request)
    root = _rejected_root(library_dir)
    if not root.exists():
        return []
    items = []
    for p in root.rglob("*"):
        if p.is_file():
            st = p.stat()
            items.append(RejectedItem(relative_path=str(p.relative_to(root)), size_bytes=st.st_size, mtime=st.st_mtime))
    return items


@router.post("/rejected/unreject", status_code=204)
async def unreject_image(request: Request, body: UnrejectRequest) -> None:
    library_dir = _library_dir(request)
    src = _rejected_root(library_dir) / body.relative_path
    if not src.exists():
        raise HTTPException(status_code=404, detail="Rejected file not found.")
    dst = library_dir / body.relative_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.move, str(src), str(dst))
    await _index(request).index_file(dst)
    logger.info("viewer.image_unrejected", path=str(dst))


@router.post("/rejected/empty", status_code=204)
async def empty_rejected(request: Request) -> None:
    library_dir = _library_dir(request)
    root = _rejected_root(library_dir)
    if root.exists():
        await asyncio.to_thread(shutil.rmtree, root)
    logger.info("viewer.rejected_emptied", library_dir=str(library_dir))
