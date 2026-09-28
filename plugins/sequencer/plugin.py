"""Sequencer plugin — task-queue imaging automation."""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import LogScope, PluginContext, PluginManifest
from astrolol.core.sequencer import Sequencer
from plugins.sequencer.api import router
from plugins.sequencer.service import SequencerServiceImpl
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.store import QueueStore

logger = structlog.get_logger()


class SequencerPlugin:
    manifest = PluginManifest(
        id="sequencer",
        name="Sequencer",
        version="0.2.0",
        description=(
            "Task-queue imaging sequencer — ordered exposure plans per target with slew, "
            "centering, guiding, dithering and meridian flips, resumable at any point."
        ),
        # Plate solving, PHD2, the target and object_resolver plugins are all optional:
        # the steps that need them are skipped (and reported) when they are disabled.
        requires=[],
        log_scopes=[LogScope(key="sequencer", label="Sequencer", logger="plugins.sequencer")],
    )

    def __init__(self) -> None:
        self._service: SequencerServiceImpl | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        existing = getattr(app.state, "sequencer", None)
        if existing is not None:
            raise RuntimeError("Another sequencer implementation is already registered")

        cfg = ctx.get_plugin_settings("sequencer", SequencerSettings)
        if ctx.profile_store is not None:
            store_dir = Path(ctx.profile_store._path).parent
        else:
            store_dir = Path.home() / ".local" / "share" / "astrolol"
        store = QueueStore(store_dir / "sequencer_queue.json")

        self._service = SequencerServiceImpl(app=app, bus=ctx.event_bus, settings=cfg, store=store)
        assert isinstance(self._service, Sequencer)
        app.state.sequencer = self._service
        app.include_router(router)
        logger.info(
            "sequencer.plugin_setup", queue_path=str(store.path), tasks=len(self._service.entries)
        )

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        if self._service is not None:
            await self._service.runner.shutdown()


def get_plugin() -> SequencerPlugin:
    return SequencerPlugin()
