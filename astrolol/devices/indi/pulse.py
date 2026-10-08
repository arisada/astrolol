"""Timed pulse guiding over INDI, shared by mounts and guide cameras with an ST4 output.

Both expose TELESCOPE_TIMED_GUIDE_NS (TIMED_GUIDE_N / _S) and TELESCOPE_TIMED_GUIDE_WE
(TIMED_GUIDE_W / _E), in milliseconds. The property is Busy while the pulse runs.
"""

from __future__ import annotations

import asyncio
import time

from astrolol.devices.base.pulse import PulseDirection, PulseGuideNotSupported
from astrolol.devices.indi.client import IndiClient

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


async def indi_pulse_guide(
    client: IndiClient, device_name: str, direction: PulseDirection, duration_ms: int
) -> None:
    if duration_ms <= 0:
        raise ValueError("pulse duration must be positive")
    if direction not in _AXES:
        raise ValueError(f"unknown direction {direction!r}")
    prop, element, opposite = _AXES[direction]
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
