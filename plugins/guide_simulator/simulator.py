"""GuideSimulator — a Guider implementation without hardware, with fault injection.

It produces noisy guide steps while guiding, settles after guide()/dither(), and can be
told to misbehave the way a real guider does on a cloudy night: lose the star for a while
(guiding recovers by itself), lose it for good (guiding stops, like PHD2 giving up), fail
to settle, or disconnect. Durations from the settings are multiplied by ``time_scale``;
fault durations are real seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import random
import time
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from astrolol.core.guiding import (
    GuiderBusy,
    GuiderError,
    GuiderNotConnected,
    GuiderStatus,
    GuidingHealth,
    GuidingStats,
    SettleFailed,
    SettleParams,
)
from astrolol.core.guiding.events import GuidingSettled, GuidingStateChanged
from astrolol.core.guiding.health import GuidingHealthTracker
from plugins.guide_simulator.settings import GuideSimSettings

logger = structlog.get_logger()


class SimFaults(BaseModel):
    star_lost: bool
    star_back_in_s: float | None  # None while lost = lost until cleared
    settle_failures_left: int


class GuideSimulator:
    name = "simulator"

    def __init__(
        self, bus: Any, settings: GuideSimSettings, rng: random.Random | None = None
    ) -> None:
        self._bus = bus
        self.settings = settings
        self._rng = rng or random.Random()
        self.connected = settings.connected_at_startup
        self._capturing = False  # guide() called and not stopped
        self._paused = False
        self._lost = False
        self._lost_until: float | None = None
        self._settle_failures = 0
        self._settling = False
        self._dither_offset = 0.0  # extra error (arcsec) decaying after a dither
        self._health = GuidingHealthTracker()
        self._tasks: list[asyncio.Task[None]] = []

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._step_loop(), name="guide_sim_steps"))
        self._tasks.append(asyncio.create_task(self._watch_slews(), name="guide_sim_slews"))

    async def shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    def _scaled(self, seconds: float) -> float:
        return seconds * self.settings.time_scale

    # ── Guider protocol ──────────────────────────────────────────────────

    def status(self) -> GuiderStatus:
        if not self.connected:
            state = "Disconnected"
        elif not self._capturing:
            state = "Stopped"
        elif self._paused:
            state = "Paused"
        elif self._lost:
            state = "Star lost"
        elif self._settling:
            state = "Settling"
        else:
            state = "Guiding"
        return GuiderStatus(
            guider=self.name,
            connected=self.connected,
            state=state,
            guiding=self._health.guiding,
            active=self.connected and self._capturing,
            settling=self._settling,
            pixel_scale=self.settings.pixel_scale,
        )

    def health(self) -> GuidingHealth:
        return self._health.health()

    def mark(self) -> float:
        return self._health.mark()

    def stats(self, since: float, until: float | None = None) -> GuidingStats:
        return self._health.stats(since, until)

    async def guide(
        self, settle: SettleParams, *, recalibrate: bool = False, wait_settle: bool = True
    ) -> None:
        self._require_connected()
        self._capturing = True
        self._paused = False
        logger.info("guide_simulator.guide_started", wait_settle=wait_settle)
        if wait_settle:
            await self._settle("guide", settle)
        else:
            asyncio.create_task(self._settle_quietly("guide", settle))

    async def stop(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        await self._lost_event("stopped")
        logger.info("guide_simulator.stopped")

    async def dither(self, pixels: float, ra_only: bool, settle: SettleParams) -> None:
        self._require_connected()
        if not self._capturing or self._paused:
            raise GuiderError("Cannot dither: not guiding")
        self._dither_offset = pixels * self.settings.pixel_scale
        logger.info("guide_simulator.dither", pixels=pixels, ra_only=ra_only)
        await self._settle("dither", settle)

    async def pause(self) -> None:
        self._paused = True
        await self._lost_event("paused")

    async def resume(self) -> None:
        self._paused = False

    # ── Faults ───────────────────────────────────────────────────────────

    async def lose_star(self, duration_s: float | None) -> None:
        """The star disappears (clouds). It comes back after *duration_s* real seconds,
        or only when cleared if None. Guiding keeps trying meanwhile."""
        self._lost = True
        self._lost_until = None if duration_s is None else time.monotonic() + duration_s
        logger.info("guide_simulator.fault_star_lost", duration_s=duration_s)
        await self._lost_event("star_lost")

    async def stop_guiding_fault(self) -> None:
        """Guiding gives up and stops (PHD2 after losing the star): guide() must be called
        again."""
        logger.info("guide_simulator.fault_guiding_stopped")
        self._capturing = False
        await self._lost_event("stopped")

    def fail_settles(self, count: int) -> None:
        self._settle_failures = count
        logger.info("guide_simulator.fault_settle_failures", count=count)

    async def disconnect(self) -> None:
        self.connected = False
        self._capturing = False
        await self._lost_event("disconnected")
        logger.info("guide_simulator.disconnected")

    def connect(self) -> None:
        self.connected = True
        logger.info("guide_simulator.connected")

    def clear_faults(self) -> None:
        self._lost = False
        self._lost_until = None
        self._settle_failures = 0
        logger.info("guide_simulator.faults_cleared")

    def faults(self) -> SimFaults:
        back = None
        if self._lost and self._lost_until is not None:
            back = round(max(0.0, self._lost_until - time.monotonic()), 1)
        return SimFaults(
            star_lost=self._lost, star_back_in_s=back, settle_failures_left=self._settle_failures
        )

    # ── Internals ────────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self.connected:
            raise GuiderNotConnected("The guide simulator is disconnected")

    def _star_visible(self) -> bool:
        if self._lost and self._lost_until is not None and time.monotonic() >= self._lost_until:
            self._lost = False
            self._lost_until = None
        return not self._lost

    def _producing_steps(self) -> bool:
        return self.connected and self._capturing and not self._paused and self._star_visible()

    async def _lost_event(self, reason: str) -> None:
        if self._health.on_lost(reason):
            await self._bus.publish(
                GuidingStateChanged(guider=self.name, guiding=False, reason=reason)
            )

    async def _step_loop(self) -> None:
        while True:
            await asyncio.sleep(self._scaled(self.settings.step_interval_s))
            if self._producing_steps():
                sigma = self.settings.rms_arcsec / math.sqrt(2)
                offset = self._dither_offset
                self._dither_offset *= 0.3
                ra = self._rng.gauss(0.0, sigma) + offset
                dec = self._rng.gauss(0.0, sigma)
                if self._health.on_step(ra, dec):
                    await self._bus.publish(GuidingStateChanged(guider=self.name, guiding=True))
            elif self._capturing and self.connected and not self._paused:
                await self._lost_event("star_lost")

    async def _watch_slews(self) -> None:
        q = self._bus.subscribe()
        try:
            while True:
                event = await q.get()
                if (
                    getattr(event, "type", "") == "mount.slew_started"
                    and self.settings.lose_star_on_slew
                    and self._capturing
                ):
                    logger.warning("guide_simulator.slewed_while_guiding")
                    self._capturing = False
                    await self._lost_event("star_lost")
        finally:
            self._bus.unsubscribe(q)

    async def _settle(self, after: Literal["guide", "dither"], settle: SettleParams) -> None:
        if self._settling:
            raise GuiderBusy("Already settling")
        self._settling = True
        error: str | None = None
        try:
            if self._settle_failures > 0:
                self._settle_failures -= 1
                await asyncio.sleep(self._scaled(settle.timeout))
                error = "timed-out waiting for guider to settle"
            else:
                deadline = time.monotonic() + self._scaled(
                    settle.time + self.settings.settle_extra_s
                )
                timeout_at = time.monotonic() + self._scaled(settle.timeout)
                # Settling needs guide steps: wait while the star is lost (it may come back)
                while time.monotonic() < deadline or not self._health.guiding:
                    if not self.connected or not self._capturing:
                        error = "guiding stopped while settling"
                        break
                    if time.monotonic() >= timeout_at:
                        error = "timed-out waiting for guider to settle"
                        break
                    await asyncio.sleep(min(0.05, self._scaled(0.5)))
        finally:
            self._settling = False
        await self._bus.publish(GuidingSettled(guider=self.name, after=after, error=error))
        logger.info("guide_simulator.settled", after=after, error=error)
        if error:
            raise SettleFailed(error)

    async def _settle_quietly(
        self, after: Literal["guide", "dither"], settle: SettleParams
    ) -> None:
        with contextlib.suppress(GuiderError):
            await self._settle(after, settle)
