"""Property values pinned to a device: set again every time it connects.

A driver forgets some of what the user sets (INDI saves `CCD_TEMP_RAMP` but does not restore it),
and a few of those values matter: a cooling ramp of 0 can damage a sensor. A pin keeps the value
with the device's inventory item (``connect_params["pinned_props"]``) and astrolol writes it back
once the driver is connected and has announced its properties.

A pin is ``{"values": {element: number or text}}`` or ``{"on_elements": [switch, ...]}``, the same
shape as pre-connect properties.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import structlog

logger = structlog.get_logger()

PINNED_KEY = "pinned_props"

# Setting these again at every connection would start, stop or save something.
NEVER_PINNED = frozenset({
    "CONNECTION", "CCD_EXPOSURE", "CCD_ABORT_EXPOSURE", "CONFIG_PROCESS", "CCD_GAIN",
})
SETTLE_S = 1.0  # wait before looking whether the driver took the values
PROPERTY_WAIT_S = 5.0


def is_gain(element: str) -> bool:
    """A gain is always given explicitly with the exposure, never kept as a device default."""
    return element.lower() == "gain"


def pinnable(name: str, kind: str, permission: str, switch_rule: str | None) -> bool:
    """Can this property be pinned? *kind*: number | text | switch | light | blob."""
    if name in NEVER_PINNED or permission != "rw":
        return False
    if kind in ("number", "text"):
        return True
    return kind == "switch" and switch_rule in ("1ofmany", "nofmany")  # not "at most one": triggers


def pin_spec(kind: str, elements: Mapping[str, Any]) -> dict[str, Any] | None:
    """The pin for a property's current *elements* (name -> value; switches: bool), or None
    when there is nothing to keep."""
    if kind == "switch":
        on = [name for name, value in elements.items() if value]
        return {"on_elements": on} if on else None
    values: dict[str, Any] = {}
    for name, value in elements.items():
        if is_gain(name) or value is None:
            continue
        values[name] = float(value) if kind == "number" else str(value)
    return {"values": values} if values else None


def clean_pins(raw: Any) -> dict[str, dict[str, Any]]:
    """The valid pins of a hand-edited JSON value; anything malformed is left out."""
    if not isinstance(raw, dict):
        return {}
    pins: dict[str, dict[str, Any]] = {}
    for name, spec in raw.items():
        if name in NEVER_PINNED or not isinstance(spec, dict):
            continue
        if isinstance(spec.get("on_elements"), list):
            pins[name] = {"on_elements": [str(e) for e in spec["on_elements"]]}
        elif isinstance(spec.get("values"), dict) and spec["values"]:
            pins[name] = {"values": {k: v for k, v in spec["values"].items() if not is_gain(k)}}
    return pins


async def apply_pins(client: Any, device_name: str, raw_pins: Any) -> list[str]:
    """Write the pins to the connected device. Returns the properties that could not be set
    (not offered by the driver, refused, or left in the Alert state by it)."""
    pins = clean_pins(raw_pins)
    failed: list[str] = []
    applied: list[str] = []
    for prop, spec in pins.items():
        try:
            vector = await client.wait_for_property(device_name, prop, timeout=PROPERTY_WAIT_S)
            if "on_elements" in spec:
                await client.set_switch(device_name, prop, spec["on_elements"])
            elif vector.vectortype == "NumberVector":
                await client.set_number(device_name, prop, {k: float(v) for k, v in spec["values"].items()})
            else:
                await client.set_text(device_name, prop, {k: str(v) for k, v in spec["values"].items()})
            applied.append(prop)
        except Exception as exc:
            logger.warning("device.pinned_property_failed", device=device_name, prop=prop, error=str(exc) or type(exc).__name__)
            failed.append(prop)
    if applied:
        await asyncio.sleep(SETTLE_S)
        for prop in applied:
            state = client._vector_state(device_name, prop)
            if state == "Alert":
                logger.warning("device.pinned_property_refused", device=device_name, prop=prop)
                failed.append(prop)
    if pins:
        logger.info("device.pinned_properties_applied", device=device_name, applied=applied, failed=failed)
    return failed
