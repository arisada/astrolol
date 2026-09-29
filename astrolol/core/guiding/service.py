"""The ``Guider`` protocol — the interface, with no logic — and its registration helper.

A guiding plugin (PHD2, the guide simulator, a future built-in guider) registers one
implementation as ``app.state.guider`` with ``register_guider()``. Consumers (the
sequencer, the imager's loop dithering) depend only on this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from astrolol.core.guiding.models import GuiderStatus, GuidingHealth, GuidingStats, SettleParams

if TYPE_CHECKING:
    from astrolol.imaging.models import DitherConfig


@runtime_checkable
class Guider(Protocol):
    name: str

    def status(self) -> GuiderStatus: ...

    def health(self) -> GuidingHealth: ...

    def mark(self) -> float:
        """A point in time to measure guiding from (see stats)."""
        ...

    def stats(self, since: float, until: float | None = None) -> GuidingStats:
        """RMS, unguided seconds and guiding losses between two marks."""
        ...

    async def guide(
        self, settle: SettleParams, *, recalibrate: bool = False, wait_settle: bool = True
    ) -> None:
        """Start guiding. With *wait_settle*, return once settled.

        Raises GuiderNotConnected, or SettleFailed when settling fails or times out.
        """
        ...

    async def stop(self) -> None:
        """Stop guiding (and capture). No-op when not guiding."""
        ...

    async def dither(self, pixels: float, ra_only: bool, settle: SettleParams) -> None:
        """Dither and return once settled. Raises GuiderNotConnected / SettleFailed."""
        ...

    async def pause(self) -> None: ...

    async def resume(self) -> None: ...


def register_guider(app: Any, guider: Guider) -> None:
    """Make *guider* the application's guider and wire the imager's loop dithering to it.

    Only one guider can be active: registering a second one is an error.
    """
    existing = getattr(app.state, "guider", None)
    if existing is not None and existing is not guider:
        raise RuntimeError(
            f"A guider is already registered ({existing.name}); enable only one guiding plugin"
        )
    app.state.guider = guider
    imager = getattr(app.state, "imager_manager", None)
    if imager is not None:

        async def dither(cfg: DitherConfig) -> None:
            await guider.dither(
                cfg.pixels,
                cfg.ra_only,
                SettleParams(
                    pixels=cfg.settle_pixels, time=cfg.settle_time, timeout=cfg.settle_timeout
                ),
            )

        imager.set_dither_hook(dither)


def unregister_guider(app: Any, guider: Guider) -> None:
    if getattr(app.state, "guider", None) is guider:
        app.state.guider = None
        imager = getattr(app.state, "imager_manager", None)
        if imager is not None:
            imager.set_dither_hook(None)
