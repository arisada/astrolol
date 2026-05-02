"""Object resolver plugin — offline-first astronomical name resolution."""
from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest

from plugins.object_resolver.api import router
from plugins.object_resolver.catalog import ObjectCatalog
from plugins.object_resolver.settings import ObjectResolverSettings

logger = structlog.get_logger()


class ObjectResolverPlugin:
    manifest = PluginManifest(
        id="object_resolver",
        name="Object Resolver",
        version="0.1.0",
        description=(
            "Offline-first astronomical object name resolver. Resolves NGC, IC, "
            "Messier, and common names to J2000 coordinates and vice-versa. "
            "Powered by the OpenNGC catalog and Astropy (planets/Moon/Sun). "
            "Optional online Simbad fallback for unrecognised names."
        ),
        log_scopes=[LogScope(key="object_resolver", label="Object Resolver", logger="plugins.object_resolver")],
    )

    def __init__(self) -> None:
        self._catalog: ObjectCatalog | None = None
        self._app: FastAPI | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("object_resolver", ObjectResolverSettings)
        db_path = Path(cfg.db_path).expanduser()

        self._catalog = ObjectCatalog(db_path)
        self._catalog.open()
        self._app = app

        app.state.object_resolver_catalog = self._catalog
        app.state.object_resolver_settings = cfg
        app.state.object_resolver_syncing = False

        app.include_router(router)
        logger.info("object_resolver.plugin_setup", db_path=str(db_path))

    async def startup(self) -> None:
        if self._catalog is None or self._catalog.is_populated():
            return
        logger.info("object_resolver.catalog_empty_syncing")
        if self._app is not None:
            self._app.state.object_resolver_syncing = True
        try:
            await self._catalog.sync()
        except Exception:
            logger.exception("object_resolver.sync_failed_on_startup")
        finally:
            if self._app is not None:
                self._app.state.object_resolver_syncing = False

    async def shutdown(self) -> None:
        if self._catalog is not None:
            self._catalog.close()


def get_plugin() -> ObjectResolverPlugin:
    return ObjectResolverPlugin()
