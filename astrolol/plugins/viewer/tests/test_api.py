from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from astrolol.core.plugin_api import PluginContext
from astrolol.profiles.store import ProfileStore
from astrolol.plugins.viewer.plugin import ViewerPlugin
from astrolol.plugins.viewer.tests.helpers import write_fits


def _std_header(**overrides) -> dict:
    base = dict(
        IMAGETYP="Light Frame", OBJECT="M42", EXPTIME=300.0, GAIN=100, XBINNING=1,
        FILTER="Ha", INSTRUME="cam1", **{"DATE-OBS": "2026-09-29T22:00:00"},
    )
    base.update(overrides)
    return base


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    fastapi_app = FastAPI()
    bus = EventBus()
    profile_store = ProfileStore(tmp_path / "profiles.json")
    ctx = PluginContext(
        event_bus=bus, device_manager=MagicMock(), device_registry=MagicMock(),
        profile_store=profile_store,
    )
    plugin = ViewerPlugin()
    plugin.setup(fastapi_app, ctx)
    fastapi_app.state.event_bus = bus
    fastapi_app.state.profile_store = profile_store

    # ViewerIndex.start() must run on the same event loop TestClient's ASGI portal
    # will later use for every request — not a throwaway asyncio.run() loop — since
    # the sqlite connection's asyncio.Lock is exercised across all of them. The
    # FastAPI lifespan (entered by `with TestClient(app)`) is exactly that loop, same
    # as in the real app where main.py awaits plugin.startup() in the lifespan.
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await _app.state.viewer_index.start()
        yield
        await _app.state.viewer_index.close()

    fastapi_app.router.lifespan_context = lifespan
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as c:
        yield c


def _set_library_dir(client: TestClient, path: Path) -> None:
    resp = client.put("/plugins/viewer/settings", json={"library_dir": str(path)})
    assert resp.status_code == 200


# --- Settings ---

def test_get_settings_defaults_to_the_save_template_prefix(client: TestClient) -> None:
    resp = client.get("/plugins/viewer/settings")
    assert resp.status_code == 200
    assert resp.json()["library_dir"]


def test_put_settings_persists_library_dir(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "mylib"
    _set_library_dir(client, lib)
    resp = client.get("/plugins/viewer/settings")
    assert resp.json()["library_dir"] == str(lib)


# --- Rescan ---

def test_rescan_indexes_the_library(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header())
    _set_library_dir(client, lib)

    resp = client.post("/plugins/viewer/rescan")
    assert resp.status_code == 202

    # Poll briefly for the background task to finish.
    for _ in range(50):
        if not client.get("/plugins/viewer/status").json()["rescanning"]:
            break
        time.sleep(0.02)

    resp = client.get("/plugins/viewer/images")
    assert resp.json()["total"] == 1


def test_second_concurrent_rescan_is_rejected(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    for i in range(200):
        write_fits(lib / f"{i:03d}.fits", **_std_header(OBJECT=f"o{i}"))
    _set_library_dir(client, lib)

    first = client.post("/plugins/viewer/rescan")
    assert first.status_code == 202
    second = client.post("/plugins/viewer/rescan")
    assert second.status_code == 409

    for _ in range(200):
        if not client.get("/plugins/viewer/status").json()["rescanning"]:
            break
        time.sleep(0.02)


# --- Images / groups ---

def _scan(client: TestClient, lib: Path) -> None:
    _set_library_dir(client, lib)
    client.post("/plugins/viewer/rescan")
    for _ in range(100):
        if not client.get("/plugins/viewer/status").json()["rescanning"]:
            return
        time.sleep(0.02)
    raise AssertionError("rescan did not finish in time")


def test_list_images_filters_by_frame_type(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "light.fits", **_std_header(IMAGETYP="Light Frame"))
    write_fits(lib / "dark.fits", **_std_header(IMAGETYP="Dark Frame", OBJECT=""))
    _scan(client, lib)

    resp = client.get("/plugins/viewer/images", params={"frame_type": ["dark"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["frame_type"] == "dark"


def test_list_groups_then_expand_via_images_endpoint(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    for i in range(3):
        write_fits(lib / f"m42_{i}.fits", **_std_header(OBJECT="M42"))
    _scan(client, lib)

    groups = client.get("/plugins/viewer/groups").json()["items"]
    assert len(groups) == 1
    g = groups[0]
    assert g["count"] == 3

    # Expanding a group is just /images with that group's own field values as filters —
    # no group_key endpoint.
    expanded = client.get("/plugins/viewer/images", params={
        "frame_type": [g["frame_type"]], "object_name": g["object_name"],
        "filter_name": g["filter_name"], "camera_name": g["camera_name"],
        "exposure_s": g["exposure_s"], "binning": g["binning"], "gain": g["gain"],
        "night": g["night"],
    })
    assert expanded.json()["total"] == 3


def test_get_image_404_for_unknown_id(client: TestClient) -> None:
    resp = client.get("/plugins/viewer/images/does-not-exist")
    assert resp.status_code == 404


# --- Preview / stats / thumbnail ---

def test_thumbnail_and_preview_and_stats(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header())
    _scan(client, lib)
    image_id = client.get("/plugins/viewer/images").json()["items"][0]["id"]

    thumb = client.get(f"/plugins/viewer/images/{image_id}/thumbnail")
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/jpeg"

    preview = client.get(f"/plugins/viewer/images/{image_id}/preview.jpg", params={"target_bg": 0.15, "shadows": -2.0})
    assert preview.status_code == 200

    stats = client.get(f"/plugins/viewer/images/{image_id}/stats")
    assert stats.status_code == 200
    assert "histogram" in stats.json()


async def test_preview_generation_serialises_under_low_memory_mode(
    app: FastAPI, tmp_path: Path
) -> None:
    """/preview.jpg decodes the full FITS frame into memory (see preview.py) — under
    low_memory_mode it must go through mem_guard so two requests for different images
    never do that at the same time (see astrolol/core/mem_guard.py).

    Stays fully async throughout (no sync TestClient calls) — ViewerIndex's internal
    asyncio.Lock binds to whichever event loop first awaits it, and mixing TestClient's
    own loop with this async test's loop raises "bound to a different event loop"."""
    import asyncio

    from astrolol.core import mem_guard as mem_guard_mod
    from httpx import ASGITransport, AsyncClient

    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header())
    write_fits(lib / "b.fits", **_std_header(OBJECT="M31"))

    await app.state.viewer_index.start()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.put("/plugins/viewer/settings", json={"library_dir": str(lib)})
            assert resp.status_code == 200
            await ac.post("/plugins/viewer/rescan")
            for _ in range(100):
                if not (await ac.get("/plugins/viewer/status")).json()["rescanning"]:
                    break
                await asyncio.sleep(0.02)

            items = (await ac.get("/plugins/viewer/images")).json()["items"]
            assert len(items) == 2
            id_a, id_b = items[0]["id"], items[1]["id"]

            order: list[str] = []

            def _fake_render_preview(cache, fits_path, out, render):
                order.append("enter")
                import time
                time.sleep(0.05)
                Path(out).write_bytes(b"\xff\xd8\xff\xd9")  # minimal JPEG
                order.append("exit")

            import astrolol.plugins.viewer.api as viewer_api
            original = viewer_api._render_preview
            viewer_api._render_preview = _fake_render_preview
            original_check = mem_guard_mod._check_fn
            mem_guard_mod.configure(lambda: True)
            try:
                await asyncio.gather(
                    ac.get(f"/plugins/viewer/images/{id_a}/preview.jpg"),
                    ac.get(f"/plugins/viewer/images/{id_b}/preview.jpg"),
                )
            finally:
                viewer_api._render_preview = original
                mem_guard_mod._check_fn = original_check
    finally:
        await app.state.viewer_index.close()

    # Semaphore(1): the first call must fully exit before the second enters.
    assert order == ["enter", "exit", "enter", "exit"]


def test_fits_download(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header())
    _scan(client, lib)
    image_id = client.get("/plugins/viewer/images").json()["items"][0]["id"]

    resp = client.get(f"/plugins/viewer/images/{image_id}/fits")
    assert resp.status_code == 200


# --- Reject / unreject ---

def test_reject_moves_the_file_and_removes_it_from_the_index(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    path = write_fits(lib / "bad.fits", **_std_header())
    _scan(client, lib)
    image_id = client.get("/plugins/viewer/images").json()["items"][0]["id"]

    resp = client.post(f"/plugins/viewer/images/{image_id}/reject")
    assert resp.status_code == 204
    assert not path.exists()
    assert (lib / "_rejected" / "bad.fits").exists()
    assert client.get("/plugins/viewer/images").json()["total"] == 0


def test_reject_then_unreject_restores_the_file(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    path = write_fits(lib / "bad.fits", **_std_header())
    _scan(client, lib)
    image_id = client.get("/plugins/viewer/images").json()["items"][0]["id"]
    client.post(f"/plugins/viewer/images/{image_id}/reject")

    resp = client.post("/plugins/viewer/rejected/unreject", json={"relative_path": "bad.fits"})
    assert resp.status_code == 204
    assert path.exists()
    assert client.get("/plugins/viewer/images").json()["total"] == 1


def test_empty_rejected_permanently_deletes(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "bad.fits", **_std_header())
    _scan(client, lib)
    image_id = client.get("/plugins/viewer/images").json()["items"][0]["id"]
    client.post(f"/plugins/viewer/images/{image_id}/reject")

    resp = client.post("/plugins/viewer/rejected/empty")
    assert resp.status_code == 204
    assert not (lib / "_rejected").exists()


def test_rejected_dir_is_excluded_from_scanning(client: TestClient, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    path = write_fits(lib / "bad.fits", **_std_header())
    _scan(client, lib)
    image_id = client.get("/plugins/viewer/images").json()["items"][0]["id"]
    client.post(f"/plugins/viewer/images/{image_id}/reject")

    _scan(client, lib)  # rescan must not pick the rejected file back up
    assert client.get("/plugins/viewer/images").json()["total"] == 0
