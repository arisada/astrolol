"""Phd2Guider — the core Guider protocol on top of Phd2Client."""

from __future__ import annotations

from collections.abc import Awaitable

from astrolol.core.guiding import (
    GuiderError,
    GuiderNotConnected,
    GuiderStatus,
    GuidingHealth,
    GuidingStats,
    SettleFailed,
    SettleParams,
)
from plugins.phd2.client import Phd2Client

# PHD2 app states in which capture is running (to be stopped before a slew)
_INACTIVE_STATES = {"Stopped", "Disconnected", "Unknown"}


class Phd2Guider:
    name = "phd2"

    def __init__(self, client: Phd2Client) -> None:
        self._client = client

    def status(self) -> GuiderStatus:
        s = self._client.get_status()
        return GuiderStatus(
            guider=self.name,
            connected=s.connected,
            state=s.state,
            guiding=self._client.guiding_health().guiding,
            active=s.connected and s.state not in _INACTIVE_STATES,
            settling=self._client._settle_event is not None,
            pixel_scale=s.pixel_scale,
        )

    def health(self) -> GuidingHealth:
        return self._client.guiding_health()

    def mark(self) -> float:
        return self._client.mark()

    def stats(self, since: float, until: float | None = None) -> GuidingStats:
        return self._client.guiding_stats(since, until)

    async def guide(
        self, settle: SettleParams, *, recalibrate: bool = False, wait_settle: bool = True
    ) -> None:
        await _mapped(
            self._client.guide(
                settle_pixels=settle.pixels,
                settle_time=settle.time,
                settle_timeout=settle.timeout,
                recalibrate=recalibrate,
                wait_settle=wait_settle,
            )
        )

    async def stop(self) -> None:
        if not self._client.get_status().connected:
            return
        await _mapped(self._client.stop_capture())

    async def dither(self, pixels: float, ra_only: bool, settle: SettleParams) -> None:
        await _mapped(
            self._client.dither(
                pixels=pixels,
                ra_only=ra_only,
                settle_pixels=settle.pixels,
                settle_time=settle.time,
                settle_timeout=settle.timeout,
            )
        )

    async def pause(self) -> None:
        await _mapped(self._client.pause())

    async def resume(self) -> None:
        await _mapped(self._client.resume())


async def _mapped(call: Awaitable[None]) -> None:
    """Translate Phd2Client exceptions into the core guiding errors."""
    try:
        await call
    except ConnectionError as exc:
        raise GuiderNotConnected(str(exc) or "PHD2 is not connected") from exc
    except TimeoutError as exc:
        raise SettleFailed("PHD2 settle timed out") from exc
    except RuntimeError as exc:
        if "settle failed" in str(exc):
            raise SettleFailed(str(exc)) from exc
        raise GuiderError(str(exc)) from exc
