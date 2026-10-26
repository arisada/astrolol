"""Finding Alpaca servers: UDP discovery, management API, and the plugin's routes.

The UDP part runs against a fake responder on a free port; the management API against a fake
HTTP transport; the last tests against OmniSim (skipped without it).
"""
from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.plugins.alpaca import discovery
from astrolol.plugins.alpaca.discovery import (
    AlpacaServerInfo,
    broadcast_addresses,
    describe_server,
    discover_servers,
    find_servers,
    parse_address,
)


class _Responder(asyncio.DatagramProtocol):
    """An Alpaca discovery responder answering with *answer*."""

    def __init__(self, answer: bytes) -> None:
        self.answer = answer
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:  # noqa: ANN001
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # noqa: ANN001
        if data == b"alpacadiscovery1" and self.transport is not None:
            self.transport.sendto(self.answer, addr)


async def _responder(answer: bytes) -> tuple[asyncio.DatagramTransport, int]:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: _Responder(answer), local_addr=("127.0.0.1", 0))
    return transport, transport.get_extra_info("sockname")[1]


async def test_discovery_finds_a_server() -> None:
    transport, port = await _responder(json.dumps({"AlpacaPort": 4567}).encode())
    try:
        assert await discover_servers(0.3, addresses=["127.0.0.1"], port=port) == [("127.0.0.1", 4567)]
    finally:
        transport.close()


async def test_discovery_ignores_what_is_not_an_answer() -> None:
    transport, port = await _responder(b"hello")
    try:
        assert await discover_servers(0.3, addresses=["127.0.0.1"], port=port) == []
    finally:
        transport.close()


async def test_discovery_with_nobody_listening() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert await discover_servers(0.2, addresses=["127.0.0.1"], port=free) == []


def test_broadcast_addresses() -> None:
    found = broadcast_addresses()
    assert "127.0.0.1" in found and "255.255.255.255" in found
    assert len(found) == len(set(found))


@pytest.mark.parametrize("text, expected", [
    ("192.168.1.20", ("192.168.1.20", 11111)),
    ("192.168.1.20:32323", ("192.168.1.20", 32323)),
    ("seestar.local:4700", ("seestar.local", 4700)),
    ("[fe80::1]:11111", ("fe80::1", 11111)),
    ("[fe80::1]", ("fe80::1", 11111)),
    ("fe80::1", ("fe80::1", 11111)),
])
def test_parse_address(text: str, expected: tuple[str, int]) -> None:
    assert parse_address(text) == expected


@pytest.mark.parametrize("text", ["", "host:", "host:0", "host:99999", "host:abc", "bad:address:here:", "-x", "a b"])
def test_parse_bad_address(text: str) -> None:
    with pytest.raises(ValueError):
        parse_address(text)


def _management(devices: list[dict], name: str = "Rig") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/description"):
            value: object = {"ServerName": name, "Manufacturer": "Maker", "ManufacturerVersion": "1.0",
                             "Location": "Garden"}
        else:
            value = devices
        return httpx.Response(200, json={"Value": value, "ErrorNumber": 0, "ErrorMessage": ""})
    return httpx.MockTransport(handler)


_DEVICES = [
    {"DeviceName": "Cam", "DeviceType": "Camera", "DeviceNumber": 0, "UniqueID": "a"},
    {"DeviceName": "Scope", "DeviceType": "Telescope", "DeviceNumber": 0, "UniqueID": "b"},
    {"DeviceName": "Roof", "DeviceType": "Dome", "DeviceNumber": 0, "UniqueID": "c"},
]


async def test_describe_a_server() -> None:
    server = await describe_server("rig.local", 11111, transport=_management(_DEVICES))
    assert (server.name, server.manufacturer, server.location) == ("Rig", "Maker", "Garden")
    kinds = {d.name: (d.kind, d.adapter_key) for d in server.devices}
    assert kinds == {"Cam": ("camera", "alpaca_camera"), "Scope": ("mount", "alpaca_mount"),
                     "Roof": (None, None)}   # no dome support yet


async def test_one_server_found_twice_is_listed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    async def found(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return [("192.168.1.5", 11111), ("127.0.0.1", 11111)]

    async def describe(host: str, port: int, **_kwargs) -> AlpacaServerInfo:  # noqa: ANN003
        return await describe_server(host, port, transport=_management(_DEVICES))

    monkeypatch.setattr(discovery, "discover_servers", found)
    monkeypatch.setattr(discovery, "describe_server", describe)
    servers, errors = await find_servers()
    assert [(s.host, s.port) for s in servers] == [("127.0.0.1", 11111)]   # this machine: loopback
    assert errors == []


async def test_addresses_that_fail_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    async def nothing(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return []

    monkeypatch.setattr(discovery, "discover_servers", nothing)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    servers, errors = await find_servers([f"127.0.0.1:{closed}", "bad:address:here:"])
    assert servers == []
    assert {e.address: e.error for e in errors} == {
        f"127.0.0.1:{closed}": "no answer",
        "bad:address:here:": "not an address: 'bad:address:here:'",
    }


# ---------------------------------------------------------------------------
# Against OmniSim, through the plugin's routes
# ---------------------------------------------------------------------------

async def test_describe_omnisim(omnisim) -> None:  # noqa: ANN001
    server = await describe_server(omnisim.host, omnisim.port)
    assert server.name and len(server.devices) == 10
    supported = sorted(d.adapter_key for d in server.devices if d.adapter_key)
    assert supported == ["alpaca_camera", "alpaca_filter_wheel", "alpaca_flat_panel", "alpaca_focuser",
                         "alpaca_mount", "alpaca_rotator"]


async def test_omnisim_answers_discovery(omnisim) -> None:  # noqa: ANN001
    # Another OmniSim on this machine may answer too: ours must be among the answers.
    found = await discover_servers(1.0, addresses=["127.0.0.1"])
    assert ("127.0.0.1", omnisim.port) in found


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path):  # noqa: ANN001, ANN201
    from astrolol.config.settings import settings
    from astrolol.main import create_app
    from astrolol.profiles.store import ProfileStore

    monkeypatch.setattr(settings, "profiles_file", tmp_path / "profiles.json")
    monkeypatch.setattr(settings, "inventory_file", tmp_path / "inventory.json")
    monkeypatch.setattr(discovery, "broadcast_addresses", lambda: ["127.0.0.1"])   # not the LAN
    store = ProfileStore(settings.profiles_file)
    store.update_user_settings(store.get_user_settings().model_copy(update={"enabled_plugins": ["alpaca"]}))
    return create_app()


def _client(app) -> AsyncClient:  # noqa: ANN001
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30.0)


async def test_discover_route_and_connected_devices(app, omnisim) -> None:  # noqa: ANN001
    async with _client(app) as c:
        r = await c.post("/plugins/alpaca/discover", json={"addresses": ["127.0.0.1:1"]})
        assert r.status_code == 200, r.text
        body = r.json()
        ours = [s for s in body["servers"] if s["port"] == omnisim.port]
        assert ours and any(d["adapter_key"] == "alpaca_focuser" for d in ours[0]["devices"])
        assert body["errors"] == [{"address": "127.0.0.1:1", "error": "no answer"}]

        assert (await c.get("/plugins/alpaca/connected")).json() == []
        r = await c.post("/devices/connect", json={
            "device_id": "afoc", "kind": "focuser", "adapter_key": "alpaca_focuser",
            "params": {"host": omnisim.host, "port": omnisim.port, "device_number": 0},
        })
        assert r.status_code == 201, r.text
        connected = (await c.get("/plugins/alpaca/connected")).json()
        assert connected == [{
            "device_id": "afoc", "kind": "focuser", "adapter_key": "alpaca_focuser", "state": "connected",
            "host": omnisim.host, "port": omnisim.port, "device_number": 0,
        }]
        await c.delete("/devices/connected/afoc")


async def test_saved_addresses_are_asked_at_every_scan(app, omnisim) -> None:  # noqa: ANN001
    async with _client(app) as c:
        assert (await c.get("/plugins/alpaca/settings")).json() == {"addresses": []}
        address = f"{omnisim.host}:{omnisim.port}"
        r = await c.put("/plugins/alpaca/settings", json={"addresses": [address]})
        assert r.status_code == 200
        r = await c.post("/plugins/alpaca/discover", json={})
        assert any(s["port"] == omnisim.port for s in r.json()["servers"])
        assert len([s for s in r.json()["servers"] if s["port"] == omnisim.port]) == 1   # found twice, listed once
        r = await c.put("/plugins/alpaca/settings", json={"addresses": [f"a{i}" for i in range(21)]})
        assert r.status_code == 422
