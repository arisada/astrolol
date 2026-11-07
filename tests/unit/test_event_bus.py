import pytest
from astrolol.core.events import EventBus, DeviceConnected, DeviceStateChanged, LogEvent
from astrolol.core.events.bus import HISTORY_SIZE
from astrolol.devices.base.models import DeviceState
from astrolol.core.events.models import BaseEvent


@pytest.mark.asyncio
async def test_subscriber_receives_event():
    bus = EventBus()
    q = bus.subscribe()

    event = DeviceConnected(device_kind="camera", device_key="indi_camera")
    await bus.publish(event)

    received = await q.get()
    assert received.id == event.id
    assert received.type == "device.connected"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()

    event = LogEvent(level="info", component="test", message="hello")
    await bus.publish(event)

    r1 = await q1.get()
    r2 = await q2.get()
    assert r1.id == r2.id == event.id


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    assert bus.subscriber_count == 0

    await bus.publish(DeviceConnected(device_kind="mount", device_key="indi_mount"))
    assert q.empty()


@pytest.mark.asyncio
async def test_unsubscribe_idempotent():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.unsubscribe(q)  # should not raise


@pytest.mark.asyncio
async def test_device_state_changed_event():
    bus = EventBus()
    q = bus.subscribe()

    event = DeviceStateChanged(
        device_kind="camera",
        device_key="indi_camera",
        old_state=DeviceState.DISCONNECTED,
        new_state=DeviceState.CONNECTED,
    )
    await bus.publish(event)

    received = await q.get()
    assert received.type == "device.state_changed"  # type: ignore[attr-defined]
    assert received.new_state == DeviceState.CONNECTED  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_event_json_roundtrip():
    """Events must serialize cleanly — WebSocket sends JSON to clients."""
    event = DeviceConnected(device_kind="focuser", device_key="indi_focuser")
    json_str = event.model_dump_json()
    assert '"type":"device.connected"' in json_str
    assert event.id in json_str


# ── History ring buffer ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_empty_on_new_bus():
    bus = EventBus()
    assert bus.get_history() == []


@pytest.mark.asyncio
async def test_history_contains_published_events():
    bus = EventBus()
    e1 = LogEvent(level="info", component="test", message="first")
    e2 = LogEvent(level="info", component="test", message="second")
    await bus.publish(e1)
    await bus.publish(e2)

    history = bus.get_history()
    assert len(history) == 2
    assert history[0].id == e1.id   # oldest first
    assert history[1].id == e2.id


@pytest.mark.asyncio
async def test_history_does_not_require_subscriber():
    """Events published before any subscriber still appear in history."""
    bus = EventBus()
    event = DeviceConnected(device_kind="camera", device_key="indi_cam")
    await bus.publish(event)

    # Subscribe *after* publish — history should still capture it
    history = bus.get_history()
    assert any(e.id == event.id for e in history)


@pytest.mark.asyncio
async def test_history_respects_maxlen():
    bus = EventBus()
    events = [LogEvent(level="info", component="test", message=f"msg{i}") for i in range(HISTORY_SIZE + 5)]
    for e in events:
        await bus.publish(e)

    history = bus.get_history()
    assert len(history) == HISTORY_SIZE
    # Oldest events were evicted; newest are retained
    assert history[-1].id == events[-1].id
    assert history[0].id == events[5].id  # first 5 were evicted


@pytest.mark.asyncio
async def test_history_and_subscriber_both_receive():
    """Existing subscribers still receive events when history is also populated."""
    bus = EventBus()
    q = bus.subscribe()

    event = LogEvent(level="warning", component="test", message="concurrent")
    await bus.publish(event)

    received = await q.get()
    history = bus.get_history()

    assert received.id == event.id
    assert any(e.id == event.id for e in history)


@pytest.mark.asyncio
async def test_get_history_returns_snapshot():
    """get_history() returns a list copy; later publishes don't mutate it."""
    bus = EventBus()
    await bus.publish(LogEvent(level="info", component="test", message="a"))
    snapshot = bus.get_history()
    await bus.publish(LogEvent(level="info", component="test", message="b"))
    assert len(snapshot) == 1  # snapshot is frozen


@pytest.mark.asyncio
async def test_bounded_subscriber_drops_oldest():
    bus = EventBus()
    q = bus.subscribe(maxsize=3)
    events = [LogEvent(level="info", component="t", message=str(i)) for i in range(5)]
    for e in events:
        await bus.publish(e)

    assert [q.get_nowait().id for _ in range(3)] == [e.id for e in events[2:]]
    assert bus.dropped_total == 2


@pytest.mark.asyncio
async def test_unbounded_subscriber_never_drops():
    bus = EventBus()
    q = bus.subscribe()
    for i in range(50):
        await bus.publish(LogEvent(level="info", component="t", message=str(i)))
    assert q.qsize() == 50
    assert bus.dropped_total == 0


# ── Snapshot events: only the latest is kept in the history ──────────────────────────

class _State(BaseEvent):
    snapshot = True
    type: str = "test.state"
    n: int = 0


@pytest.mark.asyncio
async def test_history_keeps_only_the_latest_snapshot_of_each_type():
    bus = EventBus()
    first = LogEvent(level="info", component="test", message="before")
    await bus.publish(first)
    for n in range(500):
        await bus.publish(_State(n=n))
    last = LogEvent(level="info", component="test", message="after")
    await bus.publish(last)

    history = bus.get_history()

    assert [e.id for e in history[:2]] == [first.id, last.id]     # ordinary events keep their order
    assert [e.n for e in history if e.type == "test.state"] == [499]
    assert history[-1].n == 499                                    # snapshots are replayed last
    assert len(history) == 3


@pytest.mark.asyncio
async def test_subscribers_still_receive_every_snapshot():
    bus = EventBus()
    q = bus.subscribe()
    for n in range(3):
        await bus.publish(_State(n=n))
    assert [(await q.get()).n for _ in range(3)] == [0, 1, 2]


@pytest.mark.asyncio
async def test_snapshots_do_not_use_up_the_ring():
    bus = EventBus()
    for n in range(HISTORY_SIZE * 2):
        await bus.publish(_State(n=n))
    logs = [LogEvent(level="info", component="test", message=f"m{i}") for i in range(10)]
    for e in logs:
        await bus.publish(e)
    assert [e.id for e in bus.get_history() if e.type == "log"] == [e.id for e in logs]
