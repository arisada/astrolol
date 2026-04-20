"""
Unit tests for the Stellarium binary telescope server.

Tests connect a real TCP socket and exchange binary packets exactly as
Stellarium's Telescope Control plugin would.
"""
from __future__ import annotations

import asyncio
import socket
import struct
import time
from typing import AsyncGenerator

import pytest

from astrolol.devices.base.models import DeviceState, MountStatus
from plugins.stellarium.server import (
    StellariumServer,
    _GOTO_PACKET_SIZE,
    _POSITION_PACKET_SIZE,
    _encode_position,
    _decode_goto,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def make_goto_packet(ra_hours: float, dec_deg: float) -> bytes:
    """Build a Goto packet as Stellarium would send it."""
    time_us = int(time.time() * 1e6)
    ra_int = int(ra_hours * 15.0 / 360.0 * (1 << 32)) & 0xFFFFFFFF
    dec_int = int(dec_deg / 90.0 * (1 << 30))
    return struct.pack("<HHqIi", _GOTO_PACKET_SIZE, 0, time_us, ra_int, dec_int)


async def recv_position(reader: asyncio.StreamReader, timeout: float = 2.0) -> bytes:
    """Read one 24-byte CurrentPosition packet."""
    return await asyncio.wait_for(reader.readexactly(_POSITION_PACKET_SIZE), timeout=timeout)


def decode_position(data: bytes) -> tuple[float, float]:
    """Unpack a CurrentPosition packet → (ra_hours, dec_deg)."""
    length, type_, _time, ra_int, dec_int, _status = struct.unpack("<HHqIii", data)
    assert length == _POSITION_PACKET_SIZE
    assert type_ == 0
    ra_deg = ra_int / (1 << 32) * 360.0
    dec_deg = dec_int / (1 << 30) * 90.0
    return ra_deg / 15.0, dec_deg


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeDeviceManager:
    def __init__(self, ra: float = 6.0, dec: float = 45.0, connected: bool = True) -> None:
        self._ra = ra
        self._dec = dec
        self._connected = connected

    def list_connected(self) -> list[dict]:
        if not self._connected:
            return []
        return [{"device_id": "mount1", "kind": "mount", "state": "connected"}]


class _FakeMountManager:
    def __init__(self, ra: float = 6.0, dec: float = 45.0) -> None:
        self._ra = ra
        self._dec = dec
        self.calls: list[tuple] = []

    async def get_status(self, device_id: str) -> MountStatus:
        return MountStatus(state=DeviceState.CONNECTED, ra=self._ra, dec=self._dec)

    async def set_target(self, device_id: str, coord, name=None, source=None) -> None:
        self.calls.append(("set_target", coord.icrs.ra.hour, coord.icrs.dec.deg))

    async def slew(self, device_id: str) -> None:
        self.calls.append(("slew", device_id))

    async def sync(self, device_id: str, coord) -> None:
        self.calls.append(("sync", coord.icrs.ra.hour, coord.icrs.dec.deg))

    async def stop(self, device_id: str) -> None:
        self.calls.append(("stop", device_id))


@pytest.fixture
async def server_with_mount() -> AsyncGenerator[tuple[StellariumServer, _FakeMountManager], None]:
    port = find_free_port()
    dm = _FakeDeviceManager(ra=6.0, dec=45.0)
    mm = _FakeMountManager(ra=6.0, dec=45.0)
    srv = StellariumServer(port=port, device_manager=dm, mount_manager=mm)
    await srv.start()
    yield srv, mm
    await srv.stop()


@pytest.fixture
async def server_no_mount() -> AsyncGenerator[StellariumServer, None]:
    port = find_free_port()
    dm = _FakeDeviceManager(connected=False)
    mm = _FakeMountManager()
    srv = StellariumServer(port=port, device_manager=dm, mount_manager=mm)
    await srv.start()
    yield srv
    await srv.stop()


# ── Packet helper tests ───────────────────────────────────────────────────────

def test_encode_position_packet_size() -> None:
    pkt = _encode_position(6.0, 45.0)
    assert len(pkt) == _POSITION_PACKET_SIZE


def test_encode_decode_roundtrip() -> None:
    pkt = _encode_position(6.0, 45.0)
    ra_h, dec_d = decode_position(pkt)
    assert ra_h == pytest.approx(6.0, abs=1e-3)
    assert dec_d == pytest.approx(45.0, abs=1e-3)


def test_encode_decode_negative_dec() -> None:
    pkt = _encode_position(20.0, -33.5)
    ra_h, dec_d = decode_position(pkt)
    assert ra_h == pytest.approx(20.0, abs=1e-3)
    assert dec_d == pytest.approx(-33.5, abs=1e-3)


def test_decode_goto_roundtrip() -> None:
    pkt = make_goto_packet(15.5, 60.0)
    result = _decode_goto(pkt)
    assert result is not None
    ra_h, dec_d = result
    assert ra_h == pytest.approx(15.5, abs=1e-3)
    assert dec_d == pytest.approx(60.0, abs=1e-3)


def test_decode_goto_malformed_returns_none() -> None:
    assert _decode_goto(b"\x00" * 10) is None   # too short
    bad = struct.pack("<HHqIi", 99, 0, 0, 0, 0)  # wrong length field
    assert _decode_goto(bad) is None


# ── Protocol tests (real TCP socket) ─────────────────────────────────────────

async def test_server_pushes_position(server_with_mount) -> None:
    """Connecting triggers position updates within _PUSH_INTERVAL."""
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    pkt = await recv_position(reader, timeout=2.0)
    ra_h, dec_d = decode_position(pkt)

    writer.close()
    await writer.wait_closed()

    assert ra_h == pytest.approx(6.0, abs=1e-3)
    assert dec_d == pytest.approx(45.0, abs=1e-3)


async def test_server_pushes_zeros_without_mount(server_no_mount) -> None:
    """When no mount is connected, position updates contain 0/0."""
    srv = server_no_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    pkt = await recv_position(reader, timeout=2.0)
    ra_h, dec_d = decode_position(pkt)

    writer.close()
    await writer.wait_closed()

    assert ra_h == pytest.approx(0.0, abs=1e-3)
    assert dec_d == pytest.approx(0.0, abs=1e-3)


async def test_goto_slews_mount(server_with_mount) -> None:
    """Sending a Goto packet triggers set_target + slew on the mount."""
    srv, mm = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    # Wait for the first position push so the connection is fully established
    await recv_position(reader, timeout=2.0)

    writer.write(make_goto_packet(15.5, 60.0))
    await writer.drain()

    # Give the server a moment to process the packet
    await asyncio.sleep(0.1)

    writer.close()
    await writer.wait_closed()

    call_types = [c[0] for c in mm.calls]
    assert "set_target" in call_types
    assert "slew" in call_types

    st = next(c for c in mm.calls if c[0] == "set_target")
    assert st[1] == pytest.approx(15.5, abs=1e-3)   # ra_hours
    assert st[2] == pytest.approx(60.0, abs=1e-3)   # dec_deg


async def test_multiple_position_updates(server_with_mount) -> None:
    """Server sends repeated position updates at the configured interval."""
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    # Read two consecutive packets
    pkt1 = await recv_position(reader, timeout=3.0)
    pkt2 = await recv_position(reader, timeout=3.0)

    writer.close()
    await writer.wait_closed()

    # Both should carry the same (fake) position
    ra1, dec1 = decode_position(pkt1)
    ra2, dec2 = decode_position(pkt2)
    assert ra1 == pytest.approx(6.0, abs=1e-3)
    assert ra2 == pytest.approx(6.0, abs=1e-3)
    assert dec1 == pytest.approx(45.0, abs=1e-3)
    assert dec2 == pytest.approx(45.0, abs=1e-3)


async def test_multiple_clients_all_receive_position(server_with_mount) -> None:
    """All connected clients receive independent position streams."""
    srv, _ = server_with_mount

    r1, w1 = await asyncio.open_connection("localhost", srv.port)
    r2, w2 = await asyncio.open_connection("localhost", srv.port)

    pkt1, pkt2 = await asyncio.gather(
        recv_position(r1, timeout=2.0),
        recv_position(r2, timeout=2.0),
    )

    for w in (w1, w2):
        w.close()
    await asyncio.gather(w1.wait_closed(), w2.wait_closed(), return_exceptions=True)

    ra1, dec1 = decode_position(pkt1)
    ra2, dec2 = decode_position(pkt2)
    assert ra1 == pytest.approx(6.0, abs=1e-3)
    assert ra2 == pytest.approx(6.0, abs=1e-3)
    assert dec1 == pytest.approx(45.0, abs=1e-3)
    assert dec2 == pytest.approx(45.0, abs=1e-3)


async def test_client_count(server_with_mount) -> None:
    srv, _ = server_with_mount

    assert srv.client_count == 0

    r1, w1 = await asyncio.open_connection("localhost", srv.port)
    r2, w2 = await asyncio.open_connection("localhost", srv.port)
    await asyncio.sleep(0.05)
    assert srv.client_count == 2

    w1.close()
    await w1.wait_closed()
    # Drain r1 so the push task sees the disconnect
    await asyncio.sleep(0.1)
    assert srv.client_count == 1

    w2.close()
    await w2.wait_closed()
    await asyncio.sleep(0.1)
    assert srv.client_count == 0


async def test_packet_header_fields(server_with_mount) -> None:
    """Position packet has correct length and type fields."""
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    raw = await recv_position(reader, timeout=2.0)
    length, type_ = struct.unpack_from("<HH", raw)

    writer.close()
    await writer.wait_closed()

    assert length == _POSITION_PACKET_SIZE
    assert type_ == 0
