"""Timed pulse guiding over INDI, shared by mounts and guide cameras with an ST4 output.

Both expose TELESCOPE_TIMED_GUIDE_NS (TIMED_GUIDE_N / _S) and TELESCOPE_TIMED_GUIDE_WE
(TIMED_GUIDE_W / _E), in milliseconds. The property is Busy while the pulse runs.

INDIGO drivers put them on a companion device instead, named after the device with a
" (guider)" suffix ("Mount Simulator (guider)"), which has to be connected on its own.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from astrolol.devices.base.pulse import PulseDirection, PulseGuideNotSupported
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()

GUIDE_COMPANION_SUFFIX = " (guider)"

_AXES: dict[str, tuple[str, str, str]] = {
    # direction: (property, element for this direction, element for the opposite one)
    "N": ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_N", "TIMED_GUIDE_S"),
    "S": ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_S", "TIMED_GUIDE_N"),
    "W": ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_W", "TIMED_GUIDE_E"),
    "E": ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_E", "TIMED_GUIDE_W"),
}


def has_pulse_guide(client: IndiClient, device_name: str) -> bool:
    return all(
        client._get_vector(device_name, prop) is not None
        for prop in ("TELESCOPE_TIMED_GUIDE_NS", "TELESCOPE_TIMED_GUIDE_WE")
    )


def pulse_device(client: IndiClient, device_name: str) -> str:
    """The device that takes *device_name*'s guide pulses: itself, or its guide companion."""
    companion = device_name + GUIDE_COMPANION_SUFFIX
    if not has_pulse_guide(client, device_name) and has_pulse_guide(client, companion):
        return companion
    return device_name


async def connect_guide_companion(client: IndiClient, device_name: str) -> None:
    """Connect *device_name*'s guide companion, if the server has one; best effort."""
    companion = device_name + GUIDE_COMPANION_SUFFIX
    if companion not in client.list_devices():
        return
    try:
        await client.connect_device(companion)
    except Exception as exc:
        logger.warning("indi.guide_companion_connect_failed", device=companion, error=str(exc))


async def disconnect_guide_companion(client: IndiClient, device_name: str) -> None:
    companion = device_name + GUIDE_COMPANION_SUFFIX
    if companion not in client.list_devices():
        return
    try:
        await client.disconnect_device(companion)
    except Exception as exc:
        logger.debug("indi.guide_companion_disconnect_failed", device=companion, error=str(exc))


async def indi_pulse_guide(
    client: IndiClient, device_name: str, direction: PulseDirection, duration_ms: int
) -> None:
    if duration_ms <= 0:
        raise ValueError("pulse duration must be positive")
    if direction not in _AXES:
        raise ValueError(f"unknown direction {direction!r}")
    prop, element, opposite = _AXES[direction]
    device_name = pulse_device(client, device_name)
    if client._get_vector(device_name, prop) is None:
        raise PulseGuideNotSupported(f"{device_name} has no {prop}")
    started = time.monotonic()
    await client.set_number(device_name, prop, {element: float(duration_ms), opposite: 0.0})
    await client.wait_prop_busy_then_done(
        device_name, prop, busy_timeout=1.0, done_timeout=duration_ms / 1000 + 5.0
    )
    # Not every driver reports Busy for the length of the pulse (the simulators answer at
    # once), but callers rely on the pulse being over when we return.
    remaining = duration_ms / 1000 - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)
