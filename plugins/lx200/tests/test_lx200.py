"""
Unit tests for the LX200 TCP server.

Each test opens a real TCP connection to the server and exercises the
protocol directly, the same way a planetarium app would.
"""
from __future__ import annotations

import asyncio
import socket
from typing import AsyncGenerator

import pytest

from astrolol.devices.base.models import DeviceState, MountStatus
from plugins.lx200.server import Lx200Server, _ra_to_lx200, _dec_to_lx200, _parse_ra, _parse_dec


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def send(writer: asyncio.StreamWriter, cmd: str) -> None:
    """Send a raw LX200 command (adds trailing #)."""
    writer.write(f":{cmd}#".encode())
    await writer.drain()


async def recv_until_hash(reader: asyncio.StreamReader, timeout: float = 2.0) -> str:
    """Read bytes until '#' and return as a string including the '#'."""
    data = await asyncio.wait_for(reader.readuntil(b"#"), timeout=timeout)
    return data.decode("ascii")


async def recv_n(reader: asyncio.StreamReader, n: int, timeout: float = 2.0) -> str:
    """Read exactly n bytes."""
    data = await asyncio.wait_for(reader.readexactly(n), timeout=timeout)
    return data.decode("ascii")


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeDeviceManager:
    """Minimal DeviceManager stand-in with a single connected mount."""

    def __init__(self, ra: float = 6.0, dec: float = 45.0, connected: bool = True) -> None:
        self._ra = ra
        self._dec = dec
        self._connected = connected

    def list_connected(self) -> list[dict]:
        if not self._connected:
            return []
        return [{"device_id": "mount1", "kind": "mount", "state": "connected"}]


class _FakeMountManager:
    """Records all calls made by the server."""

    def __init__(self, ra: float = 6.0, dec: float = 45.0) -> None:
        self._ra = ra
        self._dec = dec
        self.calls: list[tuple] = []

    async def get_status(self, device_id: str) -> MountStatus:
        return MountStatus(
            state=DeviceState.CONNECTED,
            ra=self._ra,
            dec=self._dec,
        )

    async def set_target(self, device_id: str, coord, name=None, source=None) -> None:
        self.calls.append(("set_target", device_id, coord.icrs.ra.hour, coord.icrs.dec.deg))

    async def slew(self, device_id: str) -> None:
        self.calls.append(("slew", device_id))

    async def sync(self, device_id: str, coord) -> None:
        self.calls.append(("sync", device_id, coord.icrs.ra.hour, coord.icrs.dec.deg))

    async def stop(self, device_id: str) -> None:
        self.calls.append(("stop", device_id))


@pytest.fixture
async def server_with_mount() -> AsyncGenerator[tuple[Lx200Server, _FakeMountManager], None]:
    port = find_free_port()
    dm = _FakeDeviceManager(ra=6.0, dec=45.0)
    mm = _FakeMountManager(ra=6.0, dec=45.0)
    srv = Lx200Server(port=port, device_manager=dm, mount_manager=mm)
    await srv.start()
    yield srv, mm
    await srv.stop()


@pytest.fixture
async def server_no_mount() -> AsyncGenerator[Lx200Server, None]:
    port = find_free_port()
    dm = _FakeDeviceManager(connected=False)
    mm = _FakeMountManager()
    srv = Lx200Server(port=port, device_manager=dm, mount_manager=mm)
    await srv.start()
    yield srv
    await srv.stop()


# ── Coordinate helper tests ───────────────────────────────────────────────────

def test_ra_formatting_high_precision() -> None:
    assert _ra_to_lx200(6.0) == "06:00:00"
    assert _ra_to_lx200(12.5) == "12:30:00"
    assert _ra_to_lx200(23.999722) == "23:59:59"  # rounds to last second


def test_dec_formatting_high_precision() -> None:
    assert _dec_to_lx200(45.0) == "+45:00:00"
    assert _dec_to_lx200(-30.5) == "-30:30:00"
    assert _dec_to_lx200(0.0) == "+00:00:00"
    assert _dec_to_lx200(90.0) == "+90:00:00"


def test_ra_formatting_low_precision() -> None:
    assert _ra_to_lx200(6.0, high_precision=False) == "06:00.0"
    assert _ra_to_lx200(12.5, high_precision=False) == "12:30.0"


def test_dec_formatting_low_precision() -> None:
    assert _dec_to_lx200(45.0, high_precision=False) == "+45:00"
    assert _dec_to_lx200(-30.5, high_precision=False) == "-30:30"


def test_parse_ra_high_precision() -> None:
    assert _parse_ra("06:00:00") == pytest.approx(6.0)
    assert _parse_ra("12:30:00") == pytest.approx(12.5)


def test_parse_dec_high_precision() -> None:
    assert _parse_dec("+45:00:00") == pytest.approx(45.0)
    assert _parse_dec("-30:30:00") == pytest.approx(-30.5)
    assert _parse_dec("+00:00:00") == pytest.approx(0.0)


def test_parse_ra_low_precision() -> None:
    assert _parse_ra("06:00.0") == pytest.approx(6.0)
    assert _parse_ra("12:30.0") == pytest.approx(12.5)


def test_parse_invalid() -> None:
    assert _parse_ra("garbage") is None
    assert _parse_dec("nope") is None


# ── Protocol tests (real TCP socket) ─────────────────────────────────────────

async def test_get_ra_returns_mount_position(server_with_mount) -> None:
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)
    await send(writer, "GR")
    response = await recv_until_hash(reader)
    writer.close()
    await writer.wait_closed()
    # ra=6.0 hours → 06:00:00#
    assert response == "06:00:00#"


async def test_get_dec_returns_mount_position(server_with_mount) -> None:
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)
    await send(writer, "GD")
    response = await recv_until_hash(reader)
    writer.close()
    await writer.wait_closed()
    # dec=45.0° → +45:00:00#
    assert response == "+45:00:00#"


async def test_get_ra_no_mount_returns_zeros(server_no_mount) -> None:
    srv = server_no_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)
    await send(writer, "GR")
    response = await recv_until_hash(reader)
    writer.close()
    await writer.wait_closed()
    assert response == "00:00:00#"


async def test_get_dec_no_mount_returns_zeros(server_no_mount) -> None:
    srv = server_no_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)
    await send(writer, "GD")
    response = await recv_until_hash(reader)
    writer.close()
    await writer.wait_closed()
    assert response == "+00:00:00#"


async def test_set_ra_returns_1(server_with_mount) -> None:
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)
    await send(writer, "Sr 15:30:00")
    response = await recv_n(reader, 1)
    writer.close()
    await writer.wait_closed()
    assert response == "1"


async def test_set_dec_returns_1(server_with_mount) -> None:
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)
    await send(writer, "Sd +60:00:00")
    response = await recv_n(reader, 1)
    writer.close()
    await writer.wait_closed()
    assert response == "1"


async def test_goto_triggers_set_target_and_slew(server_with_mount) -> None:
    srv, mm = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    # Two-step GoTo: set RA, set Dec, then slew
    await send(writer, "Sr 15:30:00")
    await recv_n(reader, 1)                    # "1"

    await send(writer, "Sd +60:00:00")
    await recv_n(reader, 1)                    # "1"

    await send(writer, "MS")
    response = await recv_n(reader, 1)         # "0" = slew started

    writer.close()
    await writer.wait_closed()

    assert response == "0"
    call_types = [c[0] for c in mm.calls]
    assert "set_target" in call_types
    assert "slew" in call_types

    # Verify coordinates were passed correctly
    set_target_call = next(c for c in mm.calls if c[0] == "set_target")
    assert set_target_call[2] == pytest.approx(15.5, abs=1e-3)   # RA hours
    assert set_target_call[3] == pytest.approx(60.0, abs=1e-3)   # Dec degrees


async def test_goto_without_target_returns_2(server_with_mount) -> None:
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)
    # Send :MS# without setting a target first
    await send(writer, "MS")
    response = await recv_n(reader, 1)
    writer.close()
    await writer.wait_closed()
    assert response == "2"


async def test_sync_triggers_mount_sync(server_with_mount) -> None:
    srv, mm = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    await send(writer, "Sr 20:00:00")
    await recv_n(reader, 1)

    await send(writer, "Sd -10:00:00")
    await recv_n(reader, 1)

    await send(writer, "CM")
    response = await recv_until_hash(reader)

    writer.close()
    await writer.wait_closed()

    assert response == "Synced#"
    assert any(c[0] == "sync" for c in mm.calls)
    sync_call = next(c for c in mm.calls if c[0] == "sync")
    assert sync_call[2] == pytest.approx(20.0, abs=1e-3)
    assert sync_call[3] == pytest.approx(-10.0, abs=1e-3)


async def test_abort_triggers_stop(server_with_mount) -> None:
    srv, mm = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    await send(writer, "Q")
    # :Q# has no response — give the server a moment, then check calls
    await asyncio.sleep(0.1)

    writer.close()
    await writer.wait_closed()

    assert any(c[0] == "stop" for c in mm.calls)


async def test_identify_returns_product_name(server_with_mount) -> None:
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)
    await send(writer, "GVP")
    response = await recv_until_hash(reader)
    writer.close()
    await writer.wait_closed()
    assert response == "astrolol#"


async def test_precision_toggle(server_with_mount) -> None:
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    # Default is HIGH; first :P# should toggle to LOW
    await send(writer, "P")
    response = await recv_until_hash(reader)
    assert "LOW" in response

    # Second toggle returns HIGH
    await send(writer, "P")
    response = await recv_until_hash(reader)
    assert "HIGH" in response

    writer.close()
    await writer.wait_closed()


async def test_low_precision_coordinates(server_with_mount) -> None:
    """After :U#, RA and Dec are returned in low-precision format."""
    srv, _ = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    # :U# toggles precision to low, no response
    await send(writer, "U")
    await asyncio.sleep(0.05)  # let server process

    await send(writer, "GR")
    ra_resp = await recv_until_hash(reader)  # expect "HH:MM.T#"

    await send(writer, "GD")
    dec_resp = await recv_until_hash(reader)  # expect "±DD:MM#"

    writer.close()
    await writer.wait_closed()

    # ra=6h low precision → "06:00.0#"
    assert ra_resp == "06:00.0#"
    # dec=45° low precision → "+45:00#"
    assert dec_resp == "+45:00#"


async def test_multiple_clients_independent_state(server_with_mount) -> None:
    """Two clients maintain separate pending RA/Dec state."""
    srv, mm = server_with_mount

    r1, w1 = await asyncio.open_connection("localhost", srv.port)
    r2, w2 = await asyncio.open_connection("localhost", srv.port)

    # Client 1 sets RA only
    await send(w1, "Sr 01:00:00")
    await recv_n(r1, 1)

    # Client 2 sets a different RA
    await send(w2, "Sr 23:00:00")
    await recv_n(r2, 1)

    # Client 1 sends :MS# without Dec — should return "2" (no target)
    await send(w1, "MS")
    resp1 = await recv_n(r1, 1)

    # Client 2 also sends :MS# without Dec — same
    await send(w2, "MS")
    resp2 = await recv_n(r2, 1)

    for w in (w1, w2):
        w.close()
    await asyncio.gather(w1.wait_closed(), w2.wait_closed(), return_exceptions=True)

    assert resp1 == "2"
    assert resp2 == "2"


async def test_pipelined_commands(server_with_mount) -> None:
    """Commands sent back-to-back in one write are all processed correctly."""
    srv, mm = server_with_mount
    reader, writer = await asyncio.open_connection("localhost", srv.port)

    # Send three commands in a single write
    writer.write(b":Sr 05:34:32#:Sd +22:00:52#:MS#")
    await writer.drain()

    r1 = await recv_n(reader, 1)   # "1" for :Sr#
    r2 = await recv_n(reader, 1)   # "1" for :Sd#
    r3 = await recv_n(reader, 1)   # "0" for :MS#

    writer.close()
    await writer.wait_closed()

    assert r1 == "1"
    assert r2 == "1"
    assert r3 == "0"
    assert any(c[0] == "slew" for c in mm.calls)


async def test_server_client_count(server_with_mount) -> None:
    srv, _ = server_with_mount

    assert srv.client_count == 0

    r1, w1 = await asyncio.open_connection("localhost", srv.port)
    r2, w2 = await asyncio.open_connection("localhost", srv.port)
    await asyncio.sleep(0.05)  # let connections register
    assert srv.client_count == 2

    w1.close()
    await w1.wait_closed()
    await asyncio.sleep(0.05)
    assert srv.client_count == 1

    w2.close()
    await w2.wait_closed()
    await asyncio.sleep(0.05)
    assert srv.client_count == 0
