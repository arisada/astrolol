"""Folders set in the UI stay inside the storage roots of the start-up configuration."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.api.settings import router as settings_router
from astrolol.config import settings as settings_mod
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.imaging import ImagerManager
from astrolol.imaging.imager import _expand_template
from astrolol.imaging.models import ExposureRequest
from astrolol.profiles.store import ProfileStore

OUTSIDE = "/etc/astrolol-not-a-root/%D"


def test_name_parts_stay_one_name() -> None:
    expanded = _expand_template("%O/%f/%C", "light", 1, 1.0, None,
                                object_name="../../.ssh", filter_name="..", camera_name="a/b")
    assert expanded == ".._.._.ssh/_/a_b"


async def test_a_save_folder_outside_keeps_the_frame(
    manager: DeviceManager, event_bus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_mod.settings, "storage_roots", [tmp_path / "images"])
    store = ProfileStore(tmp_path / "profiles.json")
    store.update_user_settings(store.get_user_settings().model_copy(
        update={"save_dir_template": str(tmp_path / "elsewhere"), "save_filename_template": "%N"},
    ))
    imager = ImagerManager(device_manager=manager, event_bus=event_bus,
                           images_dir=tmp_path / "images", profile_store=store)
    await manager.connect(DeviceConfig(device_id="cam1", kind="camera", adapter_key="fake_camera"))

    result = await imager.expose("cam1", ExposureRequest(duration=1.0, save=True))

    assert Path(result.fits_path).exists()            # still where the camera wrote it
    assert not (tmp_path / "elsewhere").exists()


def _settings_client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.state.profile_store = ProfileStore(tmp_path / "profiles.json")
    app.include_router(settings_router)
    return TestClient(app)


def test_settings_refuse_a_save_folder_outside(tmp_path: Path) -> None:
    client = _settings_client(tmp_path)
    body = client.get("/settings").json()
    r = client.put("/settings", json={**body, "save_dir_template": OUTSIDE})
    assert r.status_code == 422
    assert "storage_roots" in r.json()["detail"]
    assert client.get("/settings").json()["save_dir_template"] == body["save_dir_template"]
