"""Guide simulator REST routes and plugin wiring."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from astrolol.core.plugin_api import PluginContext
from astrolol.plugins.guide_simulator.plugin import get_plugin
from astrolol.plugins.guide_simulator.settings import GuideSimSettings


def _app() -> FastAPI:
    plugin = get_plugin()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await plugin.startup()
        yield
        await plugin.shutdown()

    app = FastAPI(lifespan=lifespan)
    app.state.imager_manager = None
    ctx = PluginContext(event_bus=EventBus(), device_manager=None, device_registry=None)
    plugin.setup(app, ctx)
    app.state.guide_simulator.settings = GuideSimSettings(time_scale=0.01)
    return app


def test_registers_as_the_guider() -> None:
    app = _app()
    assert app.state.guider is app.state.guide_simulator


def test_guide_faults_and_status() -> None:
    with TestClient(_app()) as client:
        assert client.post("/plugins/guide_simulator/guide").status_code == 204
        deadline = time.monotonic() + 3
        while not client.get("/plugins/guide_simulator/status").json()["health"]["guiding"]:
            assert time.monotonic() < deadline
            time.sleep(0.01)

        assert (
            client.post(
                "/plugins/guide_simulator/faults/star_loss", json={"duration_s": None}
            ).status_code
            == 204
        )
        body = client.get("/plugins/guide_simulator/status").json()
        assert body["faults"]["star_lost"] is True
        assert body["health"]["reason"] == "star_lost"
        assert body["status"]["state"] == "Star lost"

        assert client.post("/plugins/guide_simulator/faults/clear").status_code == 204
        assert (
            client.post(
                "/plugins/guide_simulator/faults/settle_failures", json={"count": 2}
            ).status_code
            == 204
        )
        assert (
            client.get("/plugins/guide_simulator/status").json()["faults"]["settle_failures_left"]
            == 2
        )

        assert client.post("/plugins/guide_simulator/disconnect").status_code == 204
        assert client.post("/plugins/guide_simulator/guide").status_code == 409


def test_settings_roundtrip() -> None:
    with TestClient(_app()) as client:
        s = client.get("/plugins/guide_simulator/settings").json()
        s["rms_arcsec"] = 1.7
        assert client.put("/plugins/guide_simulator/settings", json=s).json()["rms_arcsec"] == 1.7
