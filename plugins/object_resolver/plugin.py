"""Object resolver plugin — offline-first astronomical name resolution."""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest

from plugins.object_resolver.api import router
from plugins.object_resolver.catalog import ObjectCatalog
from plugins.object_resolver.service import ObjectResolverService
from plugins.object_resolver.settings import ObjectResolverSettings

logger = structlog.get_logger()


class ObjectResolverPlugin:
    manifest = PluginManifest(
        id="object_resolver",
        name="Object Resolver",
        version="0.1.0",
        description=(
            "Offline-first astronomical object name resolver. Resolves NGC, IC, "
            "Messier, Sharpless (Sh2), Hipparcos star, and common names to J2000 "
            "coordinates and vice-versa. Powered by the OpenNGC, Sharpless, and "
            "Hipparcos catalogs and Astropy (planets/Moon/Sun). Optional online "
            "Simbad fallback for unrecognised names."
        ),
        log_scopes=[LogScope(key="object_resolver", label="Object Resolver", logger="plugins.object_resolver")],
    )

    def __init__(self) -> None:
        self._catalog: ObjectCatalog | None = None
        self._app: FastAPI | None = None
        self._sync_task: asyncio.Task | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("object_resolver", ObjectResolverSettings)
        db_path = Path(cfg.db_path).expanduser()

        self._catalog = ObjectCatalog(db_path)
        self._catalog.open()
        self._app = app

        app.state.object_resolver_catalog = self._catalog
        app.state.object_resolver_settings = cfg
        app.state.object_resolver_syncing = False
        app.state.object_resolver = ObjectResolverService(app)

        app.include_router(router)
        logger.info("object_resolver.plugin_setup", db_path=str(db_path))

    async def startup(self) -> None:
        if self._catalog is None or self._catalog.is_populated():
            return
        logger.info(
            "object_resolver.catalog_empty_syncing",
            detail=(
                "first run: downloading OpenNGC (NGC/IC), Sharpless, and Hipparcos "
                "catalogs (~130k objects) in the background — search/resolve will "
                "return partial or no results from the local catalog until this "
                "finishes; check GET /plugins/object_resolver/status for progress"
            ),
        )
        if self._app is not None:
            self._app.state.object_resolver_syncing = True
        # Run in the background so a slow connection doesn't block app startup —
        # the rest of the app (devices, profiles, other plugins) keeps loading.
        self._sync_task = asyncio.create_task(self._sync_in_background())

    async def _sync_in_background(self) -> None:
        assert self._catalog is not None
        try:
            count = await self._catalog.sync()
            logger.info("object_resolver.catalog_sync_complete", object_count=count)
        except asyncio.CancelledError:
            logger.info("object_resolver.catalog_sync_cancelled")
            raise
        except Exception:
            logger.exception("object_resolver.sync_failed_on_startup")
        finally:
            if self._app is not None:
                self._app.state.object_resolver_syncing = False

    async def shutdown(self) -> None:
        if self._sync_task is not None and not self._sync_task.done():
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task
        if self._catalog is not None:
            self._catalog.close()


def get_plugin() -> ObjectResolverPlugin:
    return ObjectResolverPlugin()
