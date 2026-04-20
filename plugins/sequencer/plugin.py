"""Sequencer plugin — task-queue imaging automation."""
from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI

from astrolol.core.plugin_api import PluginContext, PluginManifest
from plugins.sequencer.api import router
from plugins.sequencer.runner import SequenceRunner
from plugins.sequencer.settings import SequencerSettings

logger = structlog.get_logger()


class SequencerPlugin:
    manifest = PluginManifest(
        id="sequencer",
        name="Sequencer",
        version="0.1.0",
        description=(
            "Task-queue imaging sequencer — run ordered exposure plans with automatic "
            "slew, plate solve, guiding, dithering, and meridian flip handling."
        ),
        requires=["platesolve", "phd2"],
    )

    def __init__(self) -> None:
        self._runner: SequenceRunner | None = None

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        cfg = ctx.get_plugin_settings("sequencer", SequencerSettings)

        # Locate the state file next to profiles.json
        if ctx.profile_store is not None:
            store_dir = Path(ctx.profile_store._path).parent
        else:
            store_dir = Path.home() / ".local" / "share" / "astrolol"
        state_path = store_dir / "sequencer_state.json"

        self._runner = SequenceRunner(
            event_bus=ctx.event_bus,
            settings=cfg,
            state_path=state_path,
        )
        self._runner.set_app(app)
        app.state.sequence_runner = self._runner
        app.include_router(router)
        logger.info("sequencer.plugin_setup", state_path=str(state_path))

    async def startup(self) -> None:
        # Resume logic: restore progress from state file for tasks already in queue.
        # (Queue is empty at startup; user adds tasks via the API.)
        pass

    async def shutdown(self) -> None:
        if self._runner is not None:
            await self._runner.cancel()


def get_plugin() -> SequencerPlugin:
    return SequencerPlugin()
