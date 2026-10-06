"""Regression test for the org.bluez.Agent1 ServiceInterface construction.

dbus_next infers each method's D-Bus signature from its return annotation and
rejects anything that isn't a type-string constant -- including a plain
``-> None`` on a void method. This doesn't need a real D-Bus connection to
catch: building the class is enough to trigger dbus_next's annotation
inspection at decoration time.
"""
from __future__ import annotations

from astrolol.devices.bluetooth.backend import _build_pairing_agent, _mac_from_device_path

_DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"


def _call(agent, method_name: str, *args):
    """dbus_next's @method() wrapper discards the return value on a direct call
    (real D-Bus dispatch calls the stored raw function instead) -- reach through
    to it so the agent's logic can be unit tested without a live bus."""
    raw_fn = getattr(type(agent), method_name).__dict__["__DBUS_METHOD"].fn
    return raw_fn(agent, *args)


def test_build_pairing_agent_does_not_raise() -> None:
    agent = _build_pairing_agent({})
    assert agent is not None


def test_agent_returns_pin_for_known_device() -> None:
    agent = _build_pairing_agent({"AA:BB:CC:DD:EE:FF": "1234"})
    assert _call(agent, "RequestPinCode", _DEVICE_PATH) == "1234"


def test_agent_falls_back_to_default_pin_for_unknown_device() -> None:
    agent = _build_pairing_agent({})
    assert _call(agent, "RequestPinCode", _DEVICE_PATH) == "0000"


def test_agent_passkey_is_numeric() -> None:
    agent = _build_pairing_agent({"AA:BB:CC:DD:EE:FF": "5678"})
    assert _call(agent, "RequestPasskey", _DEVICE_PATH) == 5678


def test_mac_from_device_path() -> None:
    assert _mac_from_device_path("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF") == "AA:BB:CC:DD:EE:FF"
