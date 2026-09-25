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


class _LimitedMount(FakeMount):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.meridian_limit: float | None = None

    async def set_meridian_limit(self, degrees: float) -> None:
        self.meridian_limit = degrees


@pytest.fixture
def limits_app(app, tmp_path):
    from astrolol.profiles.store import ProfileStore

    app.state.registry.register_mount("limited", _LimitedMount)  # type: ignore[arg-type]
    store = ProfileStore(tmp_path / "profiles.json")  # never the user's real settings file
    app.state.profile_store = store
    app.state.mount_manager._profile_store = store
    return app


@pytest.mark.asyncio
async def test_connect_applies_the_default_meridian_limit(limits_app) -> None:
    async with AsyncClient(transport=ASGITransport(app=limits_app), base_url="http://test") as c:
        await _connect(c, "limited")
    assert limits_app.state.device_manager.get_mount("m").meridian_limit == 20.0


@pytest.mark.asyncio
async def test_saving_mount_settings_pushes_the_meridian_limit(limits_app) -> None:
    async with AsyncClient(transport=ASGITransport(app=limits_app), base_url="http://test") as c:
        await _connect(c, "limited")
        r = await c.put("/mount/m/settings", json={"meridian_limit_deg": 7.5, "horizon_action": "park"})
        assert r.status_code == 200
        got = (await c.get("/mount/m/settings")).json()
    assert limits_app.state.device_manager.get_mount("m").meridian_limit == 7.5
    assert got["meridian_limit_deg"] == 7.5 and got["horizon_action"] == "park"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"meridian_limit_deg": 61}, {"meridian_limit_deg": -1},
    {"horizon_min_alt_deg": 70}, {"horizon_action": "explode"},
])
async def test_mount_limit_settings_validation(limits_app, body: dict) -> None:
    async with AsyncClient(transport=ASGITransport(app=limits_app), base_url="http://test") as c:
        r = await c.put("/mount/m/settings", json=body)
    assert r.status_code == 422
