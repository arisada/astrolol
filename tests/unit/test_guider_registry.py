"""register_guider: one active guider, wired to the imager's loop dithering."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from astrolol.core.guiding import SettleParams, register_guider, unregister_guider
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


async def test_register_wires_dithering_and_rejects_a_second_guider() -> None:
    imager = _Imager()
    app = SimpleNamespace(state=SimpleNamespace(imager_manager=imager))
    g = _Guider("one")
    register_guider(app, g)  # type: ignore[arg-type]
    assert app.state.guider is g

    await imager.hook(DitherConfig(every_frames=1, pixels=4.0, ra_only=True, settle_time=7))
    pixels, ra_only, settle = g.dithers[0]
    assert (pixels, ra_only, settle.time) == (4.0, True, 7)

    register_guider(app, g)  # type: ignore[arg-type]  # same guider again: fine
    with pytest.raises(RuntimeError, match="already registered"):
        register_guider(app, _Guider("two"))  # type: ignore[arg-type]

    unregister_guider(app, g)  # type: ignore[arg-type]
    assert app.state.guider is None and imager.hook is None
