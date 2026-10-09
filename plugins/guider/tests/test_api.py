import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from plugins.guider.api import router
from plugins.guider.controller import AxisSettings
from plugins.guider.guider import BuiltinGuider
from plugins.guider.settings import GuiderSettings
from plugins.guider.tests.rig import Rig, RigDevices


@pytest.fixture
def client():
    app = FastAPI()
    fine = AxisSettings(min_pulse_ms=2)
    guider = BuiltinGuider(
        EventBus(), GuiderSettings(exposure=0.03, calibration_steps=5), RigDevices(Rig()), ra=fine, dec=fine
    )
    app.state.builtin_guider = guider
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def test_status_when_idle(client) -> None:
    body = client.get("/plugins/guider/status").json()
    assert body["status"]["guider"] == "builtin"
    assert body["status"]["state"] == "Stopped" and not body["status"]["active"]
    assert body["calibration"] is None and body["darks"] == []
    assert body["health"]["guiding"] is False


def test_settings_round_trip(client) -> None:
    current = client.get("/plugins/guider/settings").json()
    assert current["guide_output"] == "camera"  # ST4 is the default route
    current.update(guide_output="mount", mount_id="mount1", star_count=2)
    assert client.put("/plugins/guider/settings", json=current).status_code == 200
    again = client.get("/plugins/guider/settings").json()
    assert (again["guide_output"], again["mount_id"], again["star_count"]) == ("mount", "mount1", 2)


def test_rejects_unknown_guide_output(client) -> None:
    bad = client.get("/plugins/guider/settings").json() | {"guide_output": "carrier pigeon"}
    assert client.put("/plugins/guider/settings", json=bad).status_code == 422


def test_dither_without_guiding_is_a_conflict(client) -> None:
    r = client.post("/plugins/guider/dither", json={})
    assert r.status_code == 409 and "not guiding" in r.json()["detail"]


def test_dark_capture_listing_and_clearing(client) -> None:
    client.app.state.builtin_guider._devices.rig.hidden = True  # the scope is covered
    r = client.post("/plugins/guider/darks", json={"count": 3})
    assert r.status_code == 200
    info = r.json()
    assert info["frames"] == 3 and info["exposure"] == 0.03 and info["hot_pixels"] == 0
    assert len(client.get("/plugins/guider/status").json()["darks"]) == 1
    assert client.delete("/plugins/guider/darks").status_code == 204
    assert client.get("/plugins/guider/status").json()["darks"] == []


def test_guide_then_stop(client) -> None:
    assert client.post("/plugins/guider/guide").status_code == 204
    # calibration takes a moment; the run is active meanwhile
    assert client.get("/plugins/guider/status").json()["status"]["active"]
    assert client.post("/plugins/guider/stop").status_code == 204
    assert not client.get("/plugins/guider/status").json()["status"]["active"]


def test_clear_calibration(client) -> None:
    g = client.app.state.builtin_guider
    g.calibration = object()  # type: ignore[assignment]
    assert client.delete("/plugins/guider/calibration").status_code == 204
    assert g.calibration is None


def test_changing_exposure_keeps_the_calibration(client) -> None:
    # Pulse length to displacement does not depend on the exposure, so a run can change it live.
    g = client.app.state.builtin_guider
    g.calibration = object()  # type: ignore[assignment]
    s = client.get("/plugins/guider/settings").json() | {"exposure": 0.05}
    assert client.put("/plugins/guider/settings", json=s).status_code == 200
    assert g.settings.exposure == 0.05 and g.calibration is not None


def test_view_and_frame_before_anything_is_shown(client) -> None:
    info = client.get("/plugins/guider/view").json()
    assert info["mode"] == "idle" and info["stars"] == [] and info["width"] == 0
    assert client.get("/plugins/guider/frame.jpg").status_code == 404


def test_preview_serves_a_frame_and_stars(client) -> None:
    import time

    assert client.post("/plugins/guider/preview").status_code == 204
    try:
        for _ in range(50):
            info = client.get("/plugins/guider/view").json()
            if info["stars"]:
                break
            time.sleep(0.1)
        assert info["mode"] == "preview" and info["stars"][0]["kind"] in ("primary", "companion")
        assert client.get("/plugins/guider/status").json()["status"]["state"] == "Previewing"
        img = client.get("/plugins/guider/frame.jpg", params={"v": info["version"]})
        assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
        assert img.content[:2] == b"\xff\xd8"
    finally:
        assert client.delete("/plugins/guider/preview").status_code == 204
    assert client.get("/plugins/guider/view").json()["mode"] == "idle"


def test_preview_is_refused_while_guiding(client) -> None:
    client.post("/plugins/guider/guide")
    assert client.post("/plugins/guider/preview").status_code == 409
    client.post("/plugins/guider/stop")
