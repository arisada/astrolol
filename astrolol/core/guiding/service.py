"""The ``Guider`` protocol — the interface, with no logic — and its registration helper.

A guiding plugin (the built-in guider, PHD2, the guide simulator) registers its
implementation with ``register_guider()``. Several can be enabled at once but only one is
active: ``app.state.guider`` is that one, and what consumers (the sequencer, the imager's loop
dithering) use. The user's choice is ``UserSettings.active_guider``; without a usable choice
the first of ``GUIDER_PRIORITY`` that is registered wins, so the simulator never takes over
from a real guider. The other guiders keep their pages but refuse to act
(``require_active_guider``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fastapi import HTTPException, Request

from astrolol.core.guiding.errors import GuiderBusy
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


# Plugin ids, best first: who is active when the user has not chosen (or the choice is not enabled).
GUIDER_PRIORITY = ("guider", "phd2", "guide_simulator")


class UnknownGuider(KeyError):
    """No enabled guiding plugin has this id."""


def guiders(app: Any) -> dict[str, Guider]:
    """The registered guiders by plugin id, in registration order."""
    registry = getattr(app.state, "guiders", None)
    if registry is None:
        registry = app.state.guiders = {}
    return registry  # type: ignore[no-any-return]


def active_guider_id(app: Any) -> str | None:
    return getattr(app.state, "active_guider_id", None)


def _preferred(app: Any) -> str | None:
    store = getattr(app.state, "profile_store", None)
    return store.get_user_settings().active_guider if store is not None else None


def _choose(app: Any, preferred: str | None) -> str | None:
    registry = guiders(app)
    if preferred in registry:
        return preferred
    for plugin_id in GUIDER_PRIORITY:
        if plugin_id in registry:
            return plugin_id
    return next(iter(registry), None)


def _activate(app: Any, plugin_id: str | None) -> None:
    """Make that guider the application's, and wire the imager's loop dithering to it."""
    guider = guiders(app).get(plugin_id) if plugin_id else None
    app.state.guider = guider
    app.state.active_guider_id = plugin_id if guider is not None else None
    imager = getattr(app.state, "imager_manager", None)
    if imager is None:
        return
    if guider is None:
        imager.set_dither_hook(None)
        return

    async def dither(cfg: DitherConfig) -> None:
        await guider.dither(
            cfg.pixels,
            cfg.ra_only,
            SettleParams(pixels=cfg.settle_pixels, time=cfg.settle_time, timeout=cfg.settle_timeout),
        )

    imager.set_dither_hook(dither)


def register_guider(app: Any, guider: Guider, plugin_id: str | None = None) -> None:
    """Add *guider* to the enabled ones; it becomes the active one if it is the best choice."""
    guiders(app)[plugin_id or guider.name] = guider
    _activate(app, _choose(app, _preferred(app)))


def unregister_guider(app: Any, guider: Guider) -> None:
    registry = guiders(app)
    for plugin_id in [k for k, v in registry.items() if v is guider]:
        del registry[plugin_id]
    _activate(app, _choose(app, _preferred(app)))


def select_guider(app: Any, plugin_id: str) -> None:
    """Make that guider the active one. Raises UnknownGuider, or GuiderBusy while the current
    one is guiding or trying to (stop it first)."""
    if plugin_id not in guiders(app):
        raise UnknownGuider(plugin_id)
    current = active_guider_id(app)
    if current is not None and current != plugin_id and app.state.guider.status().active:
        raise GuiderBusy(f"{current} is guiding: stop it before choosing another guider")
    _activate(app, plugin_id)


def require_active_guider(plugin_id: str) -> Callable[[Request], Awaitable[None]]:
    """Route dependency for the actions of a guiding plugin: refused (409) while another is active."""

    async def check(request: Request) -> None:
        active = active_guider_id(request.app)
        if active != plugin_id:
            raise HTTPException(
                status_code=409,
                detail=f"{plugin_id} is not the active guider"
                + (f" ({active} is)" if active else "")
                + ". Choose it as the active guider first.",
            )

    return check
