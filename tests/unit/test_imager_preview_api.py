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

    resp = client.get("/imager/cam1/preview.jpg", params={"target_bg": 0.15, "shadows": -2.0, "quality": 50})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_preview_linear_mode_ignores_stretch_params(
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


@pytest.mark.asyncio
async def test_restretch_reuses_the_exposures_preview_base(
    client: TestClient, imager_manager: ImagerManager, manager: DeviceManager, monkeypatch
) -> None:
    """Re-stretching the last exposure must not re-read its FITS file — the
    exposure already built (and cached) its binned preview base."""
    from astrolol.imaging import preview as preview_mod

    await _connected_camera(manager)
    await imager_manager.expose("cam1", ExposureRequest(duration=1.0))

    loads: list = []
    real_load = preview_mod.load_preview_base
    monkeypatch.setattr(preview_mod, "load_preview_base", lambda p, m: loads.append(p) or real_load(p, m))

    for params in ({"target_bg": 0.15}, {"shadows": -1.5}, {"mode": "linear"}):
        assert client.get("/imager/cam1/preview.jpg", params=params).status_code == 200
    assert loads == []


@pytest.mark.asyncio
async def test_preview_accepts_colour_options(
    client: TestClient, imager_manager: ImagerManager, manager: DeviceManager
) -> None:
    """Mono frames ignore the colour options rather than rejecting them."""
    await _connected_camera(manager)
    await imager_manager.expose("cam1", ExposureRequest(duration=1.0))
    for params in ({"color": "false"}, {"linked": "true"}, {"mode": "linear", "color": "false"}):
        assert client.get("/imager/cam1/preview.jpg", params=params).status_code == 200
