import pytest
from httpx import AsyncClient, ASGITransport
from astrolol.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert isinstance(data["protocol_version"], int)
    assert isinstance(data["server_version"], str)
    assert isinstance(data["enabled_plugins"], list)


@pytest.mark.asyncio
async def test_list_available_empty(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/devices/available")
    assert response.status_code == 200
    data = response.json()
    assert "cameras" in data
    assert "mounts" in data
    assert "focusers" in data


@pytest.mark.asyncio
async def test_events_history_empty_on_fresh_app(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/events/history")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_events_history_returns_published_events():
    """Events published to the bus appear in /events/history."""
    from astrolol.core.events.models import LogEvent

    app = create_app()
    bus = app.state.event_bus

    event = LogEvent(level="info", component="test", message="history test")
    await bus.publish(event)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/events/history")

    assert response.status_code == 200
    history = response.json()
    assert any(e["id"] == event.id for e in history)


@pytest.mark.asyncio
async def test_events_history_honours_limit_and_type_prefix():
    from astrolol.core.events.models import LogEvent

    app = create_app()
    bus = app.state.event_bus
    for i in range(5):
        await bus.publish(LogEvent(level="info", component="test", message=f"m{i}"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        everything = (await client.get("/events/history")).json()
        last_two = (await client.get("/events/history", params={"limit": 2})).json()
        logs = (await client.get("/events/history", params={"type_prefix": "log", "limit": 3})).json()
        none = (await client.get("/events/history", params={"type_prefix": "nothing.like.this"})).json()
        bad = await client.get("/events/history", params={"limit": 0})

    assert last_two == everything[-2:]
    assert len(logs) == 3 and all(e["type"] == "log" for e in logs)
    assert logs == [e for e in everything if e["type"] == "log"][-3:]
    assert none == []
    assert bad.status_code == 422
