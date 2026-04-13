"""HTTP tests for GET /indi/drivers and /indi/drivers/{kind}."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.devices.indi.catalog import DriverEntry
from astrolol.main import create_app

_FAKE_DRIVERS = [
    DriverEntry(label="ZWO CCD", executable="indi_asi_ccd", device_name="ZWO CCD ASI120MC",
                group="CCDs", kind="camera", manufacturer="ZWO"),
    DriverEntry(label="EQ6-R", executable="indi_eqmod_telescope", device_name="EQ6-R",
                group="Telescopes", kind="mount", manufacturer="Sky-Watcher"),
    DriverEntry(label="Moonlite", executable="indi_moonlite_focus", device_name="MoonLite",
                group="Focusers", kind="focuser", manufacturer="MoonLite"),
]


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_list_drivers_returns_200(client: AsyncClient) -> None:
    with patch("astrolol.api.indi.load_catalog", return_value=_FAKE_DRIVERS):
        async with client as c:
            r = await c.get("/indi/drivers")
    assert r.status_code == 200
    assert len(r.json()) == 3


@pytest.mark.asyncio
async def test_list_drivers_response_shape(client: AsyncClient) -> None:
    with patch("astrolol.api.indi.load_catalog", return_value=_FAKE_DRIVERS):
        async with client as c:
            r = await c.get("/indi/drivers")
    entry = r.json()[0]
    assert {"label", "executable", "device_name", "group", "kind", "manufacturer"} <= entry.keys()


@pytest.mark.asyncio
async def test_list_drivers_by_kind_camera(client: AsyncClient) -> None:
    with patch("astrolol.api.indi.load_catalog", return_value=_FAKE_DRIVERS):
        async with client as c:
            r = await c.get("/indi/drivers/camera")
    assert r.status_code == 200
    assert all(d["kind"] == "camera" for d in r.json())
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_list_drivers_by_kind_unknown_returns_empty(client: AsyncClient) -> None:
    with patch("astrolol.api.indi.load_catalog", return_value=_FAKE_DRIVERS):
        async with client as c:
            r = await c.get("/indi/drivers/rotator")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_drivers_no_indi_installed_returns_empty(client: AsyncClient) -> None:
    """When INDI catalog dir doesn't exist, endpoints return empty lists gracefully."""
    with patch("astrolol.api.indi.load_catalog", return_value=[]):
        async with client as c:
            r_all = await c.get("/indi/drivers")
            r_kind = await c.get("/indi/drivers/camera")
    assert r_all.status_code == 200
    assert r_all.json() == []
    assert r_kind.json() == []
