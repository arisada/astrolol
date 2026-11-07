"""The event stream tells a client when it can no longer trust what it has."""
from __future__ import annotations

import asyncio
import json

import pytest

from astrolol.api import events_ws
from astrolol.core.events import EventBus
from astrolol.core.events.models import BaseEvent


class Ping(BaseEvent):
    type: str = "test.ping"
    n: int = 0


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.gate: asyncio.Event | None = None

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        if self.gate is not None:
            await self.gate.wait()
        self.sent.append(json.loads(text))


async def _until(predicate, timeout: float = 2.0) -> None:  # noqa: ANN001
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_a_quiet_stream_sends_heartbeats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_ws, "HEARTBEAT_S", 0.03)
    ws, bus = FakeSocket(), EventBus()
    task = asyncio.create_task(events_ws.serve_events(ws, bus))

    await _until(lambda: sum(m["type"] == "ws.heartbeat" for m in ws.sent) >= 2)
    await bus.publish(Ping(n=1))
    await _until(lambda: any(m["type"] == "test.ping" for m in ws.sent))
    task.cancel()

    assert [m["n"] for m in ws.sent if m["type"] == "test.ping"] == [1]


async def test_events_dropped_for_a_slow_client_are_announced_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_ws, "CLIENT_QUEUE_SIZE", 2)
    ws, bus = FakeSocket(), EventBus()
    ws.gate = asyncio.Event()                         # the client reads nothing for now
    task = asyncio.create_task(events_ws.serve_events(ws, bus))
    await _until(lambda: bus.subscriber_count == 1)

    for n in range(6):
        await bus.publish(Ping(n=n))
        await asyncio.sleep(0)
    ws.gate.set()
    await _until(lambda: sum(m["type"] == "test.ping" for m in ws.sent) >= 3)
    await bus.publish(Ping(n=99))
    await _until(lambda: any(m.get("n") == 99 for m in ws.sent))
    task.cancel()

    assert [m["type"] for m in ws.sent].count("ws.resync") == 1
    first_resync = next(i for i, m in enumerate(ws.sent) if m["type"] == "ws.resync")
    assert first_resync > 0 and ws.sent[first_resync + 1]["type"] == "test.ping"   # told before the next event
    assert ws.sent[-1]["n"] == 99


async def test_the_subscription_is_released_when_the_client_goes(monkeypatch: pytest.MonkeyPatch) -> None:
    ws, bus = FakeSocket(), EventBus()
    task = asyncio.create_task(events_ws.serve_events(ws, bus))
    await _until(lambda: bus.subscriber_count == 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bus.subscriber_count == 0
