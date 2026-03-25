import pytest
from astrolol.core.events import EventBus, DeviceConnected, DeviceStateChanged, LogEvent
from astrolol.devices.base.models import DeviceState


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
