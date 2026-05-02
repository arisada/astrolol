"""Tests for EventBusForwarder — the structlog→EventBus bridge."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from astrolol.config.logging_setup import EventBusForwarder, _SKIP_LOGGERS, _logger_to_component
from astrolol.core.events.models import LogEvent


def _make_event_dict(level="info", logger="astrolol.mount.manager", message="hello"):
    return {"level": level, "logger": logger, "event": message}


# ── Passthrough behaviour ─────────────────────────────────────────────────────

def test_returns_event_dict_unchanged():
    fwd = EventBusForwarder()
    event_dict = _make_event_dict()
    result = fwd(None, "info", event_dict)
    assert result is event_dict


def test_no_op_without_bus():
    fwd = EventBusForwarder()
    # Should not raise and should return event_dict
    result = fwd(None, "info", _make_event_dict())
    assert result["event"] == "hello"


# ── Forwarding rules ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forwards_info_to_bus():
    fwd = EventBusForwarder()
    published: list[LogEvent] = []

    async def fake_publish(evt):
        published.append(evt)

    bus = MagicMock()
    bus.publish = fake_publish
    fwd.set_bus(bus)

    event_dict = _make_event_dict(level="info", message="something happened")

    async def _run():
        fwd(None, "info", event_dict)
        # Give create_task a cycle to execute
        await asyncio.sleep(0)

    await _run()
    assert len(published) == 1
    assert published[0].level == "info"
    assert published[0].message == "something happened"
    assert isinstance(published[0], LogEvent)


@pytest.mark.asyncio
async def test_forwards_warning_and_error():
    fwd = EventBusForwarder()
    published: list[LogEvent] = []

    async def fake_publish(evt):
        published.append(evt)

    bus = MagicMock()
    bus.publish = fake_publish
    fwd.set_bus(bus)

    async def _run():
        fwd(None, "warning", _make_event_dict(level="warning", message="warn msg"))
        fwd(None, "error", _make_event_dict(level="error", message="err msg"))
        await asyncio.sleep(0)

    await _run()
    assert len(published) == 2
    assert published[0].level == "warning"
    assert published[1].level == "error"


@pytest.mark.asyncio
async def test_forwards_debug():
    # Debug messages are forwarded so they appear in the live UI log panel
    # when a scope has been set to debug verbosity.
    fwd = EventBusForwarder()
    published: list = []

    async def fake_publish(evt):
        published.append(evt)

    bus = MagicMock()
    bus.publish = fake_publish
    fwd.set_bus(bus)

    async def _run():
        fwd(None, "debug", _make_event_dict(level="debug", message="verbose debug"))
        await asyncio.sleep(0)

    await _run()
    assert len(published) == 1
    assert published[0].level == "debug"
    assert published[0].message == "verbose debug"


@pytest.mark.asyncio
async def test_skips_loggers_in_skip_list():
    fwd = EventBusForwarder()
    published: list = []

    async def fake_publish(evt):
        published.append(evt)

    bus = MagicMock()
    bus.publish = fake_publish
    fwd.set_bus(bus)

    async def _run():
        for logger_name in _SKIP_LOGGERS:
            fwd(None, "info", _make_event_dict(logger=logger_name, message="skip me"))
        await asyncio.sleep(0)

    await _run()
    assert published == []


# ── Component mapping ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("logger_name,expected", [
    ("astrolol.mount.manager",   "mount"),
    ("astrolol.imaging.imager",  "imager"),
    ("astrolol.focuser.manager", "focuser"),
    ("astrolol.devices.manager",     "device"),
    ("astrolol.devices.indi.client", "indi"),
    ("astrolol.api.mount",           "api"),
    ("astrolol.profiles.store",  "profiles"),
    ("astrolol.unknown.thing",   "thing"),
    ("",                         "app"),
])
def test_logger_to_component(logger_name, expected):
    assert _logger_to_component(logger_name) == expected
