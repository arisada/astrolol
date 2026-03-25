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
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_list_available_empty(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/devices/available")
    assert response.status_code == 200
    data = response.json()
    assert "cameras" in data
    assert "mounts" in data
    assert "focusers" in data
