"""
Alpaca plugin API.

POST /plugins/alpaca/discover   — find Alpaca servers (network discovery + saved addresses) and
                                  list their devices
GET  /plugins/alpaca/connected  — the Alpaca devices astrolol has connected, and where they are
GET/PUT /plugins/alpaca/settings — the addresses asked directly at every scan
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from astrolol.plugins.alpaca.discovery import AddressError, AlpacaServerInfo, find_servers
from astrolol.plugins.alpaca.settings import AlpacaSettings

router = APIRouter(prefix="/plugins/alpaca", tags=["alpaca"])


class DiscoverRequest(BaseModel):
    # Addresses to ask besides the saved ones, as "host" or "host:port".
    addresses: list[str] = Field(default_factory=list, max_length=20)


class DiscoverResponse(BaseModel):
    servers: list[AlpacaServerInfo]
    errors: list[AddressError]


class ConnectedAlpacaDevice(BaseModel):
    device_id: str
    kind: str
    adapter_key: str
    state: str
    host: str
    port: int
    device_number: int


def _settings(request: Request) -> AlpacaSettings:
    raw = request.app.state.profile_store.get_user_settings().plugin_settings.get("alpaca", {})
    return AlpacaSettings(**raw)


@router.post("/discover", response_model=DiscoverResponse)
async def discover(body: DiscoverRequest, request: Request) -> DiscoverResponse:
    """Servers that answer discovery or are at a saved or given address, with their devices."""
    addresses = list(dict.fromkeys([*_settings(request).addresses, *body.addresses]))
    servers, errors = await find_servers(addresses)
    return DiscoverResponse(servers=servers, errors=errors)


@router.get("/connected", response_model=list[ConnectedAlpacaDevice])
async def connected(request: Request) -> list[ConnectedAlpacaDevice]:
    manager = request.app.state.device_manager
    found = []
    for d in manager.list_connected():
        if not str(d["adapter_key"]).startswith("alpaca_"):
            continue
        params = manager.get_config(d["device_id"]).params
        found.append(ConnectedAlpacaDevice(
            device_id=d["device_id"], kind=d["kind"], adapter_key=d["adapter_key"], state=d["state"],
            host=str(params.get("host", "")), port=int(params.get("port", 0)),
            device_number=int(params.get("device_number", 0)),
        ))
    return found


@router.get("/settings", response_model=AlpacaSettings)
async def get_settings(request: Request) -> AlpacaSettings:
    return _settings(request)


@router.put("/settings", response_model=AlpacaSettings)
async def put_settings(body: AlpacaSettings, request: Request) -> AlpacaSettings:
    store = request.app.state.profile_store
    current = store.get_user_settings()
    updated = {**current.plugin_settings, "alpaca": body.model_dump()}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    return body
