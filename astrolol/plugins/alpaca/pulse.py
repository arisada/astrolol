"""Pulse guiding on an Alpaca telescope or camera (both have PulseGuide and IsPulseGuiding)."""
from __future__ import annotations

import asyncio
import time

from astrolol.plugins.alpaca.client import AlpacaClient
from astrolol.devices.base.pulse import PulseDirection

# GuideDirections
_DIRECTIONS = {"N": 0, "S": 1, "E": 2, "W": 3}


async def alpaca_pulse_guide(client: AlpacaClient, direction: PulseDirection, duration_ms: int) -> None:
    """Pulse *direction* for *duration_ms*; returns when the pulse is over.

    PulseGuide may return at once (most drivers) or when done; either way IsPulseGuiding says
    when the move ends.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(f"Unknown guide direction {direction!r}")
    started = time.monotonic()
    await client.put("pulseguide", Direction=_DIRECTIONS[direction], Duration=int(duration_ms),
                     timeout=duration_ms / 1000 + 10.0)
    deadline = started + duration_ms / 1000 + 5.0
    # Sleep through most of the pulse, then ask.
    remaining = duration_ms / 1000 - (time.monotonic() - started)
    if remaining > 0.05:
        await asyncio.sleep(remaining - 0.02)
    while await client.get_or("ispulseguiding", False):
        if time.monotonic() > deadline:
            raise TimeoutError(f"pulse {direction} {duration_ms} ms still running")
        await asyncio.sleep(0.02)
