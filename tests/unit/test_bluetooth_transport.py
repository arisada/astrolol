"""Tests for BluetoothRfcommTransport's exchange framing, using a socketpair
stand-in for the RFCOMM socket (same send/recv/timeout semantics, no hardware)."""
from __future__ import annotations

import socket
import threading

import pytest

from astrolol.devices.bluetooth.transport import (
    BluetoothRfcommTransport,
    BluetoothTimeoutError,
    BluetoothTransportError,
)


class FakeManager:
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    async def open(self, device_id: str) -> socket.socket:
        return self._sock


@pytest.fixture()
def socket_pair():
    a, b = socket.socketpair()
    yield a, b
    for s in (a, b):
        try:
            s.close()
        except OSError:
            pass


async def test_request_returns_terminated_response(socket_pair) -> None:
    client_sock, peer_sock = socket_pair
    transport = BluetoothRfcommTransport(FakeManager(client_sock), "dev1", timeout=1.0)
    await transport.open()

    def _respond() -> None:
        assert peer_sock.recv(256) == b":e1\r"
        peer_sock.sendall(b"=12345\r")

    t = threading.Thread(target=_respond)
    t.start()
    response = await transport.request(b":e1\r")
    t.join(timeout=2)
    assert response == b"=12345\r"
    await transport.close()


async def test_request_times_out_with_no_response(socket_pair) -> None:
    client_sock, _peer_sock = socket_pair
    transport = BluetoothRfcommTransport(FakeManager(client_sock), "dev1", timeout=0.2)
    await transport.open()
    with pytest.raises(BluetoothTimeoutError):
        await transport.request(b":e1\r")
    await transport.close()


async def test_request_auto_reconnects_after_link_closed() -> None:
    """A dropped link self-heals transparently: the next request reopens the
    socket and retries, same as a periodic ping() would after a BT blip."""
    a1, b1 = socket.socketpair()
    a2, b2 = socket.socketpair()

    class ReconnectingManager:
        def __init__(self) -> None:
            self.sockets = [a1, a2]
            self.open_calls = 0

        async def open(self, device_id: str) -> socket.socket:
            self.open_calls += 1
            return self.sockets.pop(0)

    try:
        manager = ReconnectingManager()
        transport = BluetoothRfcommTransport(manager, "dev1", timeout=1.0)
        await transport.open()
        b1.close()  # simulate the BT link dropping

        def _respond() -> None:
            assert b2.recv(256) == b":e1\r"
            b2.sendall(b"=ok\r")

        t = threading.Thread(target=_respond)
        t.start()
        response = await transport.request(b":e1\r")
        t.join(timeout=2)

        assert response == b"=ok\r"
        assert manager.open_calls == 2
        await transport.close()
    finally:
        for s in (a1, b1, a2, b2):
            try:
                s.close()
            except OSError:
                pass


async def test_request_raises_when_reconnect_also_fails(socket_pair) -> None:
    """A genuinely-gone device (not just a blip) still surfaces as an error."""
    client_sock, peer_sock = socket_pair

    class FailingReopenManager:
        def __init__(self, sock: socket.socket) -> None:
            self._sock = sock
            self.calls = 0

        async def open(self, device_id: str) -> socket.socket:
            self.calls += 1
            if self.calls > 1:
                raise ConnectionError("no peripheral in range")
            return self._sock

    transport = BluetoothRfcommTransport(FailingReopenManager(client_sock), "dev1", timeout=1.0)
    await transport.open()
    peer_sock.close()
    with pytest.raises(BluetoothTransportError):
        await transport.request(b":e1\r")
    await transport.close()


async def test_request_before_open_raises() -> None:
    a, b = socket.socketpair()
    try:
        transport = BluetoothRfcommTransport(FakeManager(a), "dev1")
        with pytest.raises(BluetoothTransportError):
            await transport.request(b":e1\r")
    finally:
        a.close()
        b.close()
