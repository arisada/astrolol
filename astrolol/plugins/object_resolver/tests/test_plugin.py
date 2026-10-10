"""Tests for ObjectResolverPlugin startup/shutdown background sync behaviour."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from astrolol.plugins.object_resolver.catalog import ObjectCatalog
from astrolol.plugins.object_resolver.plugin import ObjectResolverPlugin


@pytest.fixture()
def plugin(tmp_path: Path) -> Generator[ObjectResolverPlugin, None, None]:
    p = ObjectResolverPlugin()
    p._catalog = ObjectCatalog(tmp_path / "test.db")
    p._catalog.open()
    app = FastAPI()
    app.state.object_resolver_syncing = False
    p._app = app
    yield p
    p._catalog.close()


async def test_startup_does_not_block_on_empty_catalog(plugin: ObjectResolverPlugin) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_sync() -> int:
        started.set()
        await release.wait()
        return 3

    plugin._catalog.sync = AsyncMock(side_effect=_slow_sync)  # type: ignore[method-assign]

    await asyncio.wait_for(plugin.startup(), timeout=1.0)  # must return immediately
    assert plugin._app.state.object_resolver_syncing is True

    await asyncio.wait_for(started.wait(), timeout=1.0)
    release.set()
    await asyncio.wait_for(plugin._sync_task, timeout=1.0)
    assert plugin._app.state.object_resolver_syncing is False


async def test_startup_skips_sync_when_already_populated(plugin: ObjectResolverPlugin) -> None:
    plugin._catalog.load_csv(
        "Name;Type;RA;Dec;Const;MajAx;MinAx;PosAng;B-Mag;V-Mag;J-Mag;H-Mag;K-Mag;SurfBr;"
        "Hubble;Pax;Pm-RA;Pm-Dec;RadVel;Redshift;Cz;M;NGC;IC;Cstar U-Mag;Cstar B-Mag;"
        "Cstar V-Mag;Identifiers;Common names;NED notes;OpenNGC notes\n"
        "NGC0224;G;00:42:44.30;+41:16:09.4;;;;;;;;;;;;;;;;;;31;;;;;;;;;"
    )
    plugin._catalog.sync = AsyncMock()  # type: ignore[method-assign]

    await plugin.startup()

    assert plugin._sync_task is None
    plugin._catalog.sync.assert_not_called()


async def test_shutdown_cancels_in_flight_sync(plugin: ObjectResolverPlugin) -> None:
    started = asyncio.Event()

    async def _hang_forever() -> int:
        started.set()
        await asyncio.Event().wait()
        return 0  # pragma: no cover — never reached

    plugin._catalog.sync = AsyncMock(side_effect=_hang_forever)  # type: ignore[method-assign]

    await plugin.startup()
    await asyncio.wait_for(started.wait(), timeout=1.0)

    await asyncio.wait_for(plugin.shutdown(), timeout=1.0)

    assert plugin._sync_task.cancelled() or plugin._sync_task.done()
    assert plugin._catalog._conn is None  # catalog.close() was called
