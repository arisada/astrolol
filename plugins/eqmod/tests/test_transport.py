"""Tests for the serial transport, run against a fake controller on a pty pair."""
from __future__ import annotations

import asyncio
import os
import select
import threading
import tty

import pytest

from plugins.eqmod.protocol import EqmodProtocolError
from plugins.eqmod.transport import EqmodTimeoutError, SerialTransport, detect_baudrate


class _FakeController:
    """Answers commands written to the pty slave from a canned command -> reply table."""

    def __init__(self) -> None:
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        self.port = os.ttyname(self.slave)
        self.responses: dict[bytes, bytes] = {}
        self.received: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        buf = b""
        while not self._stop.is_set():
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if not ready:
                continue
            try:
                buf += os.read(self.master, 256)
            except OSError:
                return
            while b"\r" in buf:
                cmd, buf = buf.split(b"\r", 1)
                cmd += b"\r"
                self.received.append(cmd)
                reply = self.responses.get(cmd)
                if reply is not None:
                    os.write(self.master, reply)

    def inject(self, data: bytes) -> None:
        os.write(self.master, data)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        os.close(self.master)
        os.close(self.slave)


@pytest.fixture
def controller():
    c = _FakeController()
    yield c
    c.close()


async def _open(port: str, timeout: float = 0.5) -> SerialTransport:
    t = SerialTransport(port, 9600, timeout=timeout)
    await t.open()
    return t


async def test_request_response_roundtrip(controller: _FakeController) -> None:
    controller.responses[b":e1\r"] = b"=031205\r"
    t = await _open(controller.port)
    try:
        assert await t.request(b":e1\r") == b"=031205\r"
    finally:
        await t.close()
    assert controller.received == [b":e1\r"]


async def test_silent_controller_times_out(controller: _FakeController) -> None:
    t = await _open(controller.port, timeout=0.2)
    try:
        with pytest.raises(EqmodTimeoutError):
            await t.request(b":e1\r")
    finally:
        await t.close()


async def test_concurrent_requests_are_serialised(controller: _FakeController) -> None:
    for axis in (1, 2):
        for cmd in "aghj":
            controller.responses[f":{cmd}{axis}\r".encode()] = f"={cmd}{axis}0000\r".encode()
    t = await _open(controller.port)
    try:
        commands = [f":{cmd}{axis}\r".encode() for axis in (1, 2) for cmd in "aghj"]
        replies = await asyncio.gather(*(t.request(c) for c in commands))
    finally:
        await t.close()
    for command, reply in zip(commands, replies):
        assert reply == b"=" + command[1:3] + b"0000\r"


async def test_stale_bytes_are_discarded_before_a_request(controller: _FakeController) -> None:
    controller.responses[b":j1\r"] = b"=000080\r"
    t = await _open(controller.port)
    try:
        controller.inject(b"=STALE\r")
        await asyncio.sleep(0.1)
        assert await t.request(b":j1\r") == b"=000080\r"
    finally:
        await t.close()


async def test_request_before_open_fails() -> None:
    with pytest.raises(EqmodProtocolError):
        await SerialTransport("/dev/null", 9600).request(b":e1\r")


# --- Baud rate auto-detection (fake transports: a pty ignores baud rate) ---

class _BaudTransport:
    def __init__(self, port: str, baudrate: int, answering_baud: int) -> None:
        self.baudrate = baudrate
        self._answering = answering_baud
        self.closed = False

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def request(self, command: bytes) -> bytes:
        if self.baudrate != self._answering:
            raise EqmodTimeoutError("garbage at the wrong baud rate")
        return b"=031205\r"


@pytest.mark.parametrize("answering_baud", [115200, 9600])
async def test_detect_baudrate_finds_the_answering_rate(answering_baud: int) -> None:
    created: list[_BaudTransport] = []

    def factory(port: str, baudrate: int) -> _BaudTransport:
        t = _BaudTransport(port, baudrate, answering_baud)
        created.append(t)
        return t

    assert await detect_baudrate("/dev/fake", transport_factory=factory) == answering_baud
    assert all(t.closed for t in created)


async def test_detect_baudrate_fails_when_nothing_answers() -> None:
    with pytest.raises(EqmodProtocolError):
        await detect_baudrate(
            "/dev/fake",
            transport_factory=lambda port, baud: _BaudTransport(port, baud, answering_baud=1),
        )
