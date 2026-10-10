"""Viewer plugin — browse, filter and inspect every FITS frame astrolol has captured."""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger()

_POLL_IDLE_S = 10.0
_POLL_BUSY_S = 5.0
_QUALITY_BATCH = 5
_DEBOUNCE_S = 1.0


class _IndexChangeDebouncer:
    """Coalesces bursts of index writes into at most one viewer.index_changed event
    per _DEBOUNCE_S, so a multi-file rescan or an ExposureCompleted burst doesn't
    trigger a re-query per file on any open Viewer tab."""

    def __init__(self, event_bus) -> None:
        self._event_bus = event_bus
        self._dirty = False
        self._task: asyncio.Task | None = None

    def notify(self) -> None:
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        from astrolol.plugins.viewer.models import ViewerIndexChangedEvent
        while self._dirty:
            self._dirty = False
            await self._event_bus.publish(ViewerIndexChangedEvent())
            await asyncio.sleep(_DEBOUNCE_S)

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


class _LiveIndexer:
    """Subscribes to ExposureCompleted and indexes any newly-saved frame that falls
    under the configured library_dir, without waiting for a manual rescan."""

    def __init__(
        self, event_bus, index, library_dir_getter, thumbs_dir: Path, debouncer: _IndexChangeDebouncer,
    ) -> None:
        self._bus = event_bus
        self._index = index
        self._library_dir_getter = library_dir_getter
        self._thumbs_dir = thumbs_dir
        self._debouncer = debouncer
        self._task: asyncio.Task | None = None
        self._q = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._consume(), name="viewer_live_indexer")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _consume(self) -> None:
        q = self._q = self._bus.subscribe()
        try:
            while True:
                event = await q.get()
                if getattr(event, "type", "") != "imager.exposure_completed":
                    continue
                await self._handle(event)
        finally:
            self._bus.unsubscribe(q)

    async def _handle(self, event) -> None:
        fits_path = getattr(event, "fits_path", None)
        if not fits_path:
            return
        library_dir = self._library_dir_getter()
        path = Path(fits_path)
        try:
            if library_dir not in path.resolve().parents and path.resolve() != library_dir:
                return
        except OSError:
            return
        try:
            await self._index.index_file(path)
            self._debouncer.notify()
            record = await self._index.get_by_path(path)
            preview_path = getattr(event, "preview_path", None)
            if record is not None and preview_path:
                from astrolol.plugins.viewer.thumbnails import ensure_thumbnail
                await ensure_thumbnail(
                    self._thumbs_dir, record.id, record.size_bytes, record.mtime, path,
                    source_preview_jpeg=Path(preview_path),
                )
        except Exception as exc:
            logger.warning("viewer.live_index_failed", path=str(path), error=str(exc))


class _QualityWorker:
    """Background, low-priority pass computing star_count/hfr for light frames.
    Yields whenever a camera is actively exposing/looping."""

    def __init__(self, index, imager_manager_getter) -> None:
        self._index = index
        self._imager_manager_getter = imager_manager_getter
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="viewer_quality_worker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def _camera_busy(self) -> bool:
        mgr = self._imager_manager_getter()
        if mgr is None:
            return False
        try:
            return any(s.state != "idle" for s in mgr.all_statuses())
        except Exception:
            return False

    async def _loop(self) -> None:
        from astrolol.plugins.viewer.quality import compute_quality
        while True:
            if self._camera_busy():
                await asyncio.sleep(_POLL_BUSY_S)
                continue
            pending = await self._index.light_frames_missing_quality(limit=_QUALITY_BATCH)
            if not pending:
                await asyncio.sleep(_POLL_IDLE_S)
                continue
            for record in pending:
                if self._camera_busy():
                    break
                bg, count, hfr = await compute_quality(Path(record.path))
                await self._index.update_quality(record.id, bg, count, hfr)
                await asyncio.sleep(0.2)


class ViewerPlugin:
    manifest = PluginManifest(
        id="viewer",
        name="Viewer",
        version="0.1.0",
        description="Browse and preview every FITS frame astrolol has captured",
        nav_order=30,
        log_scopes=[LogScope(key="viewer", label="Viewer", logger="astrolol.plugins.viewer")],
        hot_reloadable=True,
    )

    def __init__(self) -> None:
        self._app = None
        self._ctx: PluginContext | None = None
        self._index = None
        self._cache_dir: Path | None = None
        self._live_indexer: _LiveIndexer | None = None
        self._quality_worker: _QualityWorker | None = None
        self._debouncer: _IndexChangeDebouncer | None = None

    def setup(self, app: "FastAPI", ctx: PluginContext) -> None:
        from astrolol.plugins.viewer.api import router
        from astrolol.plugins.viewer.index import ViewerIndex

        data_dir = Path(ctx.profile_store._path).parent if ctx.profile_store is not None else Path.home() / ".astrolol"
        viewer_dir = data_dir / "viewer"
        index = ViewerIndex(viewer_dir / "index.sqlite3")

        app.state.viewer_index = index
        app.state.viewer_cache_dir = viewer_dir / "cache"
        app.state.viewer_thumbs_dir = viewer_dir / "thumbs"

        self._app = app
        self._ctx = ctx
        self._index = index
        self._cache_dir = viewer_dir / "cache"

        app.include_router(router)
        logger.info("viewer.plugin_setup")

    async def startup(self) -> None:
        if self._index is None or self._ctx is None or self._app is None:
            return
        await self._index.start()

        from astrolol.plugins.viewer.api import resolve_library_dir

        ctx = self._ctx
        debouncer = _IndexChangeDebouncer(ctx.event_bus)
        self._debouncer = debouncer

        live_indexer = _LiveIndexer(
            ctx.event_bus, self._index,
            lambda: resolve_library_dir(ctx.profile_store),
            self._app.state.viewer_thumbs_dir, debouncer,
        )
        live_indexer.start()
        self._live_indexer = live_indexer

        quality_worker = _QualityWorker(
            self._index, lambda: getattr(self._app.state, "imager_manager", None)
        )
        quality_worker.start()
        self._quality_worker = quality_worker

    async def shutdown(self) -> None:
        if self._live_indexer is not None:
            await self._live_indexer.stop()
        if self._quality_worker is not None:
            await self._quality_worker.stop()
        if self._debouncer is not None:
            await self._debouncer.stop()
        if self._index is not None:
            await self._index.close()


def get_plugin() -> ViewerPlugin:
    return ViewerPlugin()
