"""Tests for the status, attach and detach endpoints, against the real device manager."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from astrolol.devices.base.models import ExposureParams
from astrolol.devices.base.streaming import StreamParams
from astrolol.plugins.stacked_camera.adapters import FAST_KEY, STACKED_KEY
from astrolol.plugins.stacked_camera.tests.rig import Rig, feed, started

BASE = "/plugins/stacked_camera"


@pytest.fixture()
async def client(rig: Rig) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=rig.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_status_lists_the_real_cameras_only(rig: Rig, client: httpx.AsyncClient) -> None:
    await rig.source()
    await rig.stacked()
    body = (await client.get(f"{BASE}/status")).json()
    assert [c["device_id"] for c in body["cameras"]] == ["cam"]
    assert body["sources"] == []  # nothing has used the stream yet


async def test_status_shows_a_camera_with_virtual_ones_on_it(
    rig: Rig, client: httpx.AsyncClient
) -> None:
    await rig.source()
    await rig.stacked()
    await rig.fast()
    (camera,) = (await client.get(f"{BASE}/status")).json()["cameras"]
    assert camera["attached"] == {"stacked": "cam_stack", "fast": "cam_fast"}


async def test_status_of_a_camera_with_only_one_virtual_is_not_attached(
    rig: Rig, client: httpx.AsyncClient
) -> None:
    await rig.source()
    await rig.stacked()
    (camera,) = (await client.get(f"{BASE}/status")).json()["cameras"]
    assert camera["attached"] is None


async def test_status_reports_the_stream(rig: Rig, client: httpx.AsyncClient) -> None:
    source = await rig.source()
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=0.05, gain=90))
    for _ in range(3):
        source.emit()
        await asyncio.sleep(0.01)
    (stream,) = (await client.get(f"{BASE}/status")).json()["sources"]
    assert stream["source_id"] == "cam" and stream["running"] is True
    assert stream["sub_exposure"] == 0.05 and stream["gain"] == 90 and stream["frames"] == 3
    assert stream["error"] is None
    source.fail(RuntimeError("usb unplugged"))
    await asyncio.sleep(0.02)
    (stream,) = (await client.get(f"{BASE}/status")).json()["sources"]
    assert stream["running"] is False and "usb unplugged" in stream["error"]
    await fast.stop_stream()


async def test_attach_connects_both_cameras(rig: Rig, client: httpx.AsyncClient) -> None:
    await rig.source()
    r = await client.post(f"{BASE}/attach", json={"source_id": "cam"})
    assert r.status_code == 200
    assert r.json() == {"stacked": "cam_stack", "fast": "cam_fast"}
    adapters = {d["device_id"]: d["adapter_key"] for d in rig.manager.list_connected()}
    assert adapters["cam_stack"] == STACKED_KEY and adapters["cam_fast"] == FAST_KEY
    (camera,) = (await client.get(f"{BASE}/status")).json()["cameras"]
    assert camera["attached"] == {"stacked": "cam_stack", "fast": "cam_fast"}


async def test_attach_twice_changes_nothing(rig: Rig, client: httpx.AsyncClient) -> None:
    await rig.source()
    await client.post(f"{BASE}/attach", json={"source_id": "cam"})
    stacked = rig.manager.get_camera("cam_stack")
    r = await client.post(f"{BASE}/attach", json={"source_id": "cam"})
    assert r.status_code == 200 and rig.manager.get_camera("cam_stack") is stacked


async def test_attach_completes_a_half_attached_camera(rig: Rig, client: httpx.AsyncClient) -> None:
    await rig.source()
    stacked = await rig.stacked()
    r = await client.post(f"{BASE}/attach", json={"source_id": "cam"})
    assert r.status_code == 200
    assert rig.manager.get_camera("cam_stack") is stacked
    assert rig.manager.get_camera("cam_fast") is not None


async def test_attach_to_a_camera_that_is_not_connected_is_a_conflict(
    rig: Rig, client: httpx.AsyncClient
) -> None:
    r = await client.post(f"{BASE}/attach", json={"source_id": "nope"})
    assert r.status_code == 409 and "not connected" in r.json()["detail"]


async def test_attach_to_a_virtual_camera_is_refused(rig: Rig, client: httpx.AsyncClient) -> None:
    await rig.source()
    await client.post(f"{BASE}/attach", json={"source_id": "cam"})
    r = await client.post(f"{BASE}/attach", json={"source_id": "cam_stack"})
    assert r.status_code == 409 and "itself a stacked camera" in r.json()["detail"]


async def test_attach_with_an_id_too_long_for_a_device_is_unprocessable(
    rig: Rig, client: httpx.AsyncClient
) -> None:
    name = "c" * 62
    await rig.connect("source", name)
    r = await client.post(f"{BASE}/attach", json={"source_id": name})
    assert r.status_code == 422
    assert {d["device_id"] for d in rig.manager.list_connected()} == {name}


async def test_detach_disconnects_both_and_keeps_the_real_camera(
    rig: Rig, client: httpx.AsyncClient
) -> None:
    source = await rig.source()
    await client.post(f"{BASE}/attach", json={"source_id": "cam"})
    fast = rig.manager.get_camera("cam_fast")
    await fast.start_stream(StreamParams(exposure=0.05))
    r = await client.post(f"{BASE}/detach", json={"source_id": "cam"})
    assert r.status_code == 204
    assert {d["device_id"] for d in rig.manager.list_connected()} == {"cam"}
    assert not source.streaming


async def test_detach_with_nothing_attached_is_not_found(
    rig: Rig, client: httpx.AsyncClient
) -> None:
    await rig.source()
    r = await client.post(f"{BASE}/detach", json={"source_id": "cam"})
    assert r.status_code == 404


async def test_attached_cameras_work(rig: Rig, client: httpx.AsyncClient) -> None:
    source = await rig.source()
    await client.post(f"{BASE}/attach", json={"source_id": "cam"})
    stacked = rig.manager.get_camera("cam_stack")
    feeder = asyncio.create_task(_feed_when_started(source))
    image = await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.1)), 5)
    await feeder
    assert image.exposure_duration == pytest.approx(0.1)


async def _feed_when_started(source) -> None:  # noqa: ANN001
    await started(source)
    await feed(source, 2)


def test_attach_and_detach_need_an_administrator(rig: Rig) -> None:
    rules = {(r.path, r.level.name) for r in rig.plugin.manifest.acl_rules}
    assert ("/plugins/stacked_camera/attach", "ADMIN") in rules
    assert ("/plugins/stacked_camera/detach", "ADMIN") in rules
