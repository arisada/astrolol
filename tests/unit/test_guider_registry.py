"""The guider registry: several guiders enabled, one active, wired to the imager's loop dithering."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from astrolol.core.guiding import (
    GuiderBusy,
    SettleParams,
    UnknownGuider,
    active_guider_id,
    guiders,
    register_guider,
    select_guider,
    unregister_guider,
)
from astrolol.imaging.models import DitherConfig


class _Imager:
    def __init__(self) -> None:
        self.hook: Any = None

    def set_dither_hook(self, fn: Any) -> None:
        self.hook = fn


class _Guider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.dithers: list[tuple[float, bool, SettleParams]] = []

    async def dither(self, pixels: float, ra_only: bool, settle: SettleParams) -> None:
        self.dithers.append((pixels, ra_only, settle))


def _app(imager: Any = None, preferred: str | None = None, store: bool = True) -> SimpleNamespace:
    state = SimpleNamespace(imager_manager=imager)
    if store:
        state.profile_store = SimpleNamespace(
            get_user_settings=lambda: SimpleNamespace(active_guider=state.preferred)
        )
    state.preferred = preferred
    return SimpleNamespace(state=state)


class _Busy(_Guider):
    def __init__(self, name: str, active: bool = False) -> None:
        super().__init__(name)
        self.is_active = active

    def status(self) -> Any:
        return SimpleNamespace(active=self.is_active)


async def test_register_wires_dithering_to_the_active_guider() -> None:
    imager = _Imager()
    app = _app(imager)
    g = _Guider("one")
    register_guider(app, g, "guider")  # type: ignore[arg-type]
    assert app.state.guider is g and active_guider_id(app) == "guider"

    await imager.hook(DitherConfig(every_frames=1, pixels=4.0, ra_only=True, settle_time=7))
    pixels, ra_only, settle = g.dithers[0]
    assert (pixels, ra_only, settle.time) == (4.0, True, 7)

    unregister_guider(app, g)  # type: ignore[arg-type]
    assert app.state.guider is None and imager.hook is None and active_guider_id(app) is None


def test_several_guiders_can_be_enabled_and_the_best_one_is_active() -> None:
    app = _app()
    sim, phd2, mine = _Guider("simulator"), _Guider("phd2"), _Guider("builtin")
    register_guider(app, sim, "guide_simulator")  # type: ignore[arg-type]
    assert active_guider_id(app) == "guide_simulator"
    register_guider(app, phd2, "phd2")  # type: ignore[arg-type]
    assert active_guider_id(app) == "phd2"                       # a real guider beats the simulator
    register_guider(app, mine, "guider")  # type: ignore[arg-type]
    assert active_guider_id(app) == "guider" and app.state.guider is mine
    assert list(guiders(app)) == ["guide_simulator", "phd2", "guider"]


def test_the_saved_choice_wins_when_that_guider_is_enabled() -> None:
    app = _app(preferred="phd2")
    register_guider(app, _Guider("builtin"), "guider")  # type: ignore[arg-type]
    assert active_guider_id(app) == "guider"                     # PHD2 is not enabled (yet)
    phd2 = _Guider("phd2")
    register_guider(app, phd2, "phd2")  # type: ignore[arg-type]
    assert app.state.guider is phd2

    app.state.preferred = "not_a_plugin"
    unregister_guider(app, phd2)  # type: ignore[arg-type]
    assert active_guider_id(app) == "guider"                     # falls back when the choice is gone


async def test_choosing_another_guider_moves_the_dithering_with_it() -> None:
    imager = _Imager()
    app = _app(imager)
    mine, phd2 = _Busy("builtin"), _Busy("phd2")
    register_guider(app, mine, "guider")  # type: ignore[arg-type]
    register_guider(app, phd2, "phd2")  # type: ignore[arg-type]

    select_guider(app, "phd2")

    assert app.state.guider is phd2 and active_guider_id(app) == "phd2"
    await imager.hook(DitherConfig(every_frames=1, pixels=2.0, settle_time=3))
    assert len(phd2.dithers) == 1 and mine.dithers == []


def test_the_active_guider_cannot_be_swapped_while_it_guides() -> None:
    app = _app()
    mine, phd2 = _Busy("builtin", active=True), _Busy("phd2")
    register_guider(app, mine, "guider")  # type: ignore[arg-type]
    register_guider(app, phd2, "phd2")  # type: ignore[arg-type]

    with pytest.raises(GuiderBusy):
        select_guider(app, "phd2")
    assert app.state.guider is mine

    mine.is_active = False
    select_guider(app, "phd2")
    assert app.state.guider is phd2
    select_guider(app, "phd2")                                     # choosing the active one is always fine


def test_choosing_a_guider_that_is_not_enabled_is_an_error() -> None:
    app = _app()
    register_guider(app, _Busy("builtin"), "guider")  # type: ignore[arg-type]
    with pytest.raises(UnknownGuider):
        select_guider(app, "phd2")


def test_works_without_a_settings_store() -> None:
    app = _app(store=False)
    register_guider(app, _Guider("builtin"), "guider")  # type: ignore[arg-type]
    assert active_guider_id(app) == "guider"
