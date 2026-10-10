"""Autofocus against the INDI CCD and focuser simulators.

Reproduces a wide, coarse sweep that used to fail: 1x1 binning, 10 000-step
spacing, 5 steps either side of 36 000, so stars go from sharp to a 30+ px blur
at the extremes. The simulator draws round, Gaussian-like stars from the GSC
catalog, so every frame has plenty of obvious stars at every focus position.

Skipped when indiserver or the GSC catalog is not installed.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrolol.core.events import EventBus
from astrolol.plugins.autofocus import engine as engine_mod
from astrolol.plugins.autofocus.engine import AutofocusEngine
from astrolol.plugins.autofocus.models import AutofocusSettings
from tests.integration.test_indi_simulators import _start_indiserver, _stop


def _gsc_dir() -> str | None:
    for candidate in (os.environ.get("GSCDAT"), "/usr/share/GSC", "/usr/local/share/GSC"):
        if candidate and (Path(candidate) / "bin" / "regions.bin").exists():
            return candidate
    return None


pytestmark = pytest.mark.skipif(
    shutil.which("indiserver") is None or shutil.which("gsc") is None or _gsc_dir() is None,
    reason="indiserver and the GSC star catalog are required",
)

_PORT = 17900
_CENTRE = 36_000
_STEP = 10_000
_STEPS_EACH_SIDE = 5
# The simulator's true focus lies in this window (measured with a fine sweep).
_TRUE_FOCUS = (33_000, 39_000)


@pytest.fixture(scope="module")
async def sim_rig(tmp_path_factory: pytest.TempPathFactory):
    """Telescope pointed at a rich field, camera and focuser connected."""
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    from astrolol.devices.indi.camera import IndiCamera
    from astrolol.devices.indi.client import IndiClient
    from astrolol.devices.indi.focuser import IndiFocuser
    from astrolol.devices.indi.mount import IndiMount

    os.environ["GSCDAT"] = _gsc_dir() or ""
    server = _start_indiserver(
        _PORT, "indi_simulator_telescope", "indi_simulator_focus", "indi_simulator_ccd",
    )
    clients: list[IndiClient] = []

    async def connect() -> IndiClient:
        client = IndiClient(host="localhost", port=_PORT)
        await client.connect()
        clients.append(client)
        return client

    mount = IndiMount(device_name="Telescope Simulator", client=await connect())
    await mount.connect()
    # Orion Nebula: the simulator draws no stars where the catalog is empty (e.g. RA 0, Dec 0).
    await mount.slew(SkyCoord(ra=5.588 * u.hourangle, dec=-5.39 * u.deg, frame="icrs"))
    # Exposing mid-slew shows a different, smeared field and skews the first steps.
    await asyncio.sleep(1.0)
    for _ in range(120):
        if not (await mount.get_status()).is_slewing:
            break
        await asyncio.sleep(0.5)
    focuser = IndiFocuser(device_name="Focuser Simulator", client=await connect())
    await focuser.connect()
    camera = IndiCamera(
        device_name="CCD Simulator",
        client=await connect(),
        images_dir=tmp_path_factory.mktemp("autofocus_sim"),
    )
    await camera.connect()
    try:
        yield SimpleNamespace(camera=camera, focuser=focuser, mount=mount)
    finally:
        await camera.disconnect()
        await focuser.disconnect()
        for client in clients:
            await client.disconnect()
        _stop(server)


@pytest.fixture(scope="module")
async def sweeps(sim_rig, tmp_path_factory: pytest.TempPathFactory):
    """One autofocus run per metric (each takes ~40 s of simulated exposures), shared by the tests."""
    runs: dict[str, object] = {}
    previous_dir = engine_mod.settings.images_dir
    engine_mod.settings.images_dir = tmp_path_factory.mktemp("autofocus_images")
    devices = SimpleNamespace(
        get_camera=lambda _id: sim_rig.camera, get_focuser=lambda _id: sim_rig.focuser,
    )
    try:
        for metric in ("fwhm", "hfd"):
            await asyncio.wait_for(sim_rig.focuser.move_to(_CENTRE), timeout=60)
            settings = AutofocusSettings(
                step_size=_STEP, num_steps=_STEPS_EACH_SIDE, exposure_time=1.0, binning=1, metric=metric,
            )
            engine = AutofocusEngine(EventBus(), devices, settings_provider=lambda s=settings: s)  # type: ignore[arg-type]
            runs[metric] = await engine.focus("camera", "focuser")
        yield runs
    finally:
        engine_mod.settings.images_dir = previous_dir


def _describe(run) -> str:
    return ", ".join(f"{dp.position}:{dp.fwhm:.1f}x{dp.star_count}" for dp in run.data_points)


@pytest.mark.parametrize("metric", ["fwhm", "hfd"])
async def test_wide_sweep_finds_the_simulator_focus(sweeps, metric: str) -> None:
    run = sweeps[metric]
    assert run.status == "completed", run.error
    assert run.optimal_position is not None
    assert _TRUE_FOCUS[0] <= run.optimal_position <= _TRUE_FOCUS[1], (
        f"optimum {run.optimal_position}; points {_describe(run)}"
    )


@pytest.mark.parametrize("metric", ["fwhm", "hfd"])
async def test_every_step_sees_the_stars(sweeps, metric: str) -> None:
    """The failure mode was a handful of steps reporting one or two bogus detections
    (hot pixels, noise) while the real, defocused stars went unseen."""
    run = sweeps[metric]
    counts = [dp.star_count for dp in run.data_points]
    assert len(counts) == 2 * _STEPS_EACH_SIDE + 1
    assert min(counts) >= 0.4 * max(counts), f"star counts per step: {_describe(run)}"


@pytest.mark.parametrize("metric", ["fwhm", "hfd"])
async def test_measured_size_follows_a_defocus_curve(sweeps, metric: str) -> None:
    """Falls to a minimum and rises again, with no zigzag. (Positions below 0 are
    clamped, so the first steps repeat the same position.)"""
    run = sweeps[metric]
    sizes = [dp.fwhm for dp in run.data_points]
    lowest = sizes.index(min(sizes))
    assert 0 < lowest < len(sizes) - 1, f"minimum at a sweep end: {_describe(run)}"
    for left, right in zip(sizes[: lowest + 1], sizes[1 : lowest + 1]):
        assert right <= left * 1.1, f"size not falling towards focus: {_describe(run)}"
    for left, right in zip(sizes[lowest:], sizes[lowest + 1 :]):
        assert right >= left * 0.9, f"size not rising away from focus: {_describe(run)}"
