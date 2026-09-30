"""API tests for the on-demand live-preview render endpoint."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.api.imager import router
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.imaging import ImagerManager
from astrolol.imaging.models import ExposureRequest


async def _connected_camera(manager: DeviceManager, device_id: str = "cam1") -> str:
    config = DeviceConfig(device_id=device_id, kind="camera", adapter_key="fake_camera")
    return await manager.connect(config)


@pytest.fixture
def client(imager_manager: ImagerManager) -> TestClient:
    app = FastAPI()
    app.state.imager_manager = imager_manager
    app.include_router(router)
    return TestClient(app)


@pytest.mark.asyncio
async def test_preview_404_before_any_exposure(client: TestClient) -> None:
    resp = client.get("/imager/cam1/preview.jpg")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_preview_renders_after_exposure(
    client: TestClient, imager_manager: ImagerManager, manager: DeviceManager
) -> None:
    await _connected_camera(manager)
    await imager_manager.expose("cam1", ExposureRequest(duration=1.0))

    resp = client.get("/imager/cam1/preview.jpg", params={"black_pct": 10, "white_pct": 90, "quality": 50})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_preview_linear_mode_ignores_percentiles(
    client: TestClient, imager_manager: ImagerManager, manager: DeviceManager
) -> None:
    await _connected_camera(manager)
    await imager_manager.expose("cam1", ExposureRequest(duration=1.0))

    resp = client.get("/imager/cam1/preview.jpg", params={"mode": "linear"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_preview_reflects_the_latest_exposure_not_a_stale_one(
    client: TestClient, imager_manager: ImagerManager, manager: DeviceManager
) -> None:
    """get_last_fits_path must track the most recent exposure, not the first."""
    await _connected_camera(manager)
    await imager_manager.expose("cam1", ExposureRequest(duration=1.0))
    first_fits = imager_manager.get_last_fits_path("cam1")
    await imager_manager.expose("cam1", ExposureRequest(duration=1.0))
    second_fits = imager_manager.get_last_fits_path("cam1")

    assert first_fits != second_fits

    resp = client.get("/imager/cam1/preview.jpg")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_preview_404_when_last_fits_no_longer_exists(
    client: TestClient, imager_manager: ImagerManager, manager: DeviceManager, tmp_path
) -> None:
    await _connected_camera(manager)
    await imager_manager.expose("cam1", ExposureRequest(duration=1.0, save=False))
    # The unsaved-exposure temp path gets overwritten by the *next* unsaved exposure
    # for the same device — simulate that race by deleting it out from under the API.
    from pathlib import Path
    Path(imager_manager.get_last_fits_path("cam1")).unlink()

    resp = client.get("/imager/cam1/preview.jpg")

    assert resp.status_code == 404
