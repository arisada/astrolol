"""API tests for mount routes that have no hardware-level coverage elsewhere."""
import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.main import create_app
from tests.conftest import FakeMount


class _GuidingMount(FakeMount):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pulses: list[tuple[str, int]] = []

    async def pulse_guide(self, direction: str, duration_ms: int) -> None:
        self.pulses.append((direction, duration_ms))


@pytest.fixture
def app():
    application = create_app()
    application.state.registry.register_mount("guiding", _GuidingMount)  # type: ignore[arg-type]
    application.state.registry.register_mount("plain", FakeMount)  # type: ignore[arg-type]
    return application


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _connect(c: AsyncClient, adapter: str) -> None:
    r = await c.post("/devices/connect", json={"device_id": "m", "kind": "mount", "adapter_key": adapter})
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_pulse_guide(app, client: AsyncClient) -> None:
    async with client as c:
        await _connect(c, "guiding")
        r = await c.post("/mount/m/pulse_guide", json={"direction": "E", "duration_ms": 300})
    assert r.status_code == 204
    assert app.state.device_manager.get_mount("m").pulses == [("E", 300)]


@pytest.mark.asyncio
async def test_pulse_guide_unsupported_is_409(client: AsyncClient) -> None:
    async with client as c:
        await _connect(c, "plain")
        r = await c.post("/mount/m/pulse_guide", json={"direction": "E", "duration_ms": 300})
    assert r.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"direction": "X", "duration_ms": 100},
    {"direction": "N", "duration_ms": 0},
    {"direction": "N", "duration_ms": 10_001},
])
async def test_pulse_guide_validation(client: AsyncClient, body: dict) -> None:
    async with client as c:
        await _connect(c, "guiding")
        r = await c.post("/mount/m/pulse_guide", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_pulse_guide_unknown_device_is_404(client: AsyncClient) -> None:
    async with client as c:
        r = await c.post("/mount/nope/pulse_guide", json={"direction": "N", "duration_ms": 100})
    assert r.status_code == 404
