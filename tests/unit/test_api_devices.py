import pytest
from httpx import AsyncClient, ASGITransport

from astrolol.main import create_app
from tests.conftest import FakeCamera, FailingCamera


@pytest.fixture
def app():
    application = create_app()
    # Register test adapters directly into the registry
    application.state.registry.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    application.state.registry.register_camera("failing_camera", FailingCamera)  # type: ignore[arg-type]
    return application


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_list_available(client: AsyncClient) -> None:
    async with client as c:
        r = await c.get("/devices/available")
    assert r.status_code == 200
    assert "cameras" in r.json()


@pytest.mark.asyncio
async def test_connect_and_list(client: AsyncClient) -> None:
    async with client as c:
        r = await c.post("/devices/connect", json={
            "device_id": "cam1",
            "kind": "camera",
            "adapter_key": "fake_camera",
        })
        assert r.status_code == 201
        assert r.json()["device_id"] == "cam1"

        r = await c.get("/devices/connected")
        assert r.status_code == 200
        ids = [d["device_id"] for d in r.json()]
        assert "cam1" in ids


@pytest.mark.asyncio
async def test_connect_unknown_adapter_404(client: AsyncClient) -> None:
    async with client as c:
        r = await c.post("/devices/connect", json={
            "kind": "camera",
            "adapter_key": "does_not_exist",
        })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_connect_duplicate_409(client: AsyncClient) -> None:
    async with client as c:
        payload = {"device_id": "cam1", "kind": "camera", "adapter_key": "fake_camera"}
        await c.post("/devices/connect", json=payload)
        r = await c.post("/devices/connect", json=payload)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_connect_hardware_failure_502(client: AsyncClient) -> None:
    async with client as c:
        r = await c.post("/devices/connect", json={
            "kind": "camera",
            "adapter_key": "failing_camera",
        })
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_disconnect(client: AsyncClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json={
            "device_id": "cam1", "kind": "camera", "adapter_key": "fake_camera"
        })
        r = await c.delete("/devices/connected/cam1")
        assert r.status_code == 204

        r = await c.get("/devices/connected")
        assert r.json() == []


@pytest.mark.asyncio
async def test_disconnect_unknown_404(client: AsyncClient) -> None:
    async with client as c:
        r = await c.delete("/devices/connected/ghost")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_config_returns_full_config(client: AsyncClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json={
            "device_id": "cam1",
            "kind": "camera",
            "adapter_key": "fake_camera",
            "params": {"device_name": "Test CCD"},
        })
        r = await c.get("/devices/connected/cam1/config")
    assert r.status_code == 200
    body = r.json()
    assert body["device_id"] == "cam1"
    assert body["kind"] == "camera"
    assert body["adapter_key"] == "fake_camera"
    assert body["params"]["device_name"] == "Test CCD"


@pytest.mark.asyncio
async def test_get_config_unknown_404(client: AsyncClient) -> None:
    async with client as c:
        r = await c.get("/devices/connected/ghost/config")
    assert r.status_code == 404
