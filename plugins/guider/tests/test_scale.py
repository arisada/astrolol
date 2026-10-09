import asyncio
from types import SimpleNamespace

import pytest

from plugins.guider.scale import arcsec_per_pixel, derive_pixel_scale


def test_arcsec_per_pixel() -> None:
    assert arcsec_per_pixel(1000, 3.76) == pytest.approx(0.7756, abs=1e-3)
    assert arcsec_per_pixel(1000, 3.76, binning=2) == pytest.approx(1.5512, abs=1e-3)


def test_no_profile_means_no_scale() -> None:
    app = SimpleNamespace(state=SimpleNamespace(active_profile=None))
    assert asyncio.run(derive_pixel_scale(app, "guide_cam")) is None
    assert asyncio.run(derive_pixel_scale(app, None)) is None


def test_scale_from_the_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    import plugins.guider.scale as scale

    path = SimpleNamespace(
        ota=SimpleNamespace(focal_length=240.0), camera=SimpleNamespace(pixel_size_um=3.75), camera_device_id="cam"
    )
    monkeypatch.setattr(scale, "resolve_optical_paths", lambda *a: [path])
    app = SimpleNamespace(state=SimpleNamespace(
        active_profile=SimpleNamespace(roots=[1]), equipment_store=object(), device_manager=object()))
    assert asyncio.run(derive_pixel_scale(app, "cam")) == pytest.approx(3.223, abs=1e-3)
    assert asyncio.run(derive_pixel_scale(app, "other")) is None
