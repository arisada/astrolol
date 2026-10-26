"""The Alpaca adapters against ASCOM's OmniSim simulators.

Skipped without OmniSim (``ascom.alpaca.simulators``); see tests/alpaca_sim.py.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from astropy.io import fits

from astrolol.plugins.alpaca.camera import AlpacaCamera
from astrolol.plugins.alpaca.client import AlpacaClient, AlpacaError
from astrolol.plugins.alpaca.filter_wheel import AlpacaFilterWheel
from astrolol.plugins.alpaca.flat_panel import AlpacaFlatPanel
from astrolol.plugins.alpaca.focuser import AlpacaFocuser
from astrolol.plugins.alpaca.mount import AlpacaMount
from astrolol.plugins.alpaca.rotator import AlpacaRotator
from astrolol.devices.base.models import CoverState, DeviceState, ExposureParams, TrackingMode
from astrolol.devices.base.pulse import PulseGuideNotSupported
from astrolol.mount.sky import local_sidereal_time_h
from tests.alpaca_sim import OmniSim


def _params(sim: OmniSim) -> dict:
    return {"host": sim.host, "port": sim.port, "device_number": 0}


async def _connected(cls, sim: OmniSim, **kwargs):  # noqa: ANN001, ANN202
    device = cls(**_params(sim), **kwargs)
    await device.connect()
    return device


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

async def test_camera_exposure_writes_a_fits(omnisim, tmp_path):  # noqa: ANN001
    camera = await _connected(AlpacaCamera, omnisim, images_dir=tmp_path)
    try:
        assert camera.name == "Alpaca Camera Simulator"
        image = await camera.expose(ExposureParams(duration=0.5))
        assert (image.width, image.height) == (800, 600)
        with fits.open(image.fits_path) as hdul:
            data, header = hdul[0].data, hdul[0].header
        assert data.shape == (600, 800)               # rows × columns
        assert data.dtype == np.uint16
        assert data.max() > data.min()                 # a picture, not a blank frame
        assert header["EXPTIME"] == 0.5
        assert header["XBINNING"] == 1
        assert header["XPIXSZ"] == pytest.approx(5.6)
        assert header["INSTRUME"] == "Alpaca Camera Simulator"
        started = datetime.fromisoformat(header["DATE-OBS"]).replace(tzinfo=timezone.utc)
        assert abs((datetime.now(timezone.utc) - started).total_seconds()) < 60
        assert "BAYERPAT" not in header                # a monochrome sensor
        assert (await camera.get_status()).state == DeviceState.CONNECTED
    finally:
        await camera.disconnect()


async def test_camera_bins_and_takes_darks(omnisim, tmp_path):  # noqa: ANN001
    camera = await _connected(AlpacaCamera, omnisim, images_dir=tmp_path)
    try:
        image = await camera.expose(ExposureParams(duration=0.2, binning=2, frame_type="dark"))
        assert (image.width, image.height) == (400, 300)
        with fits.open(image.fits_path) as hdul:
            assert hdul[0].header["XBINNING"] == 2
            assert hdul[0].header["XPIXSZ"] == pytest.approx(11.2)
        # Binning comes back to 1 for the next frame.
        assert (await camera.expose(ExposureParams(duration=0.1))).width == 800
    finally:
        await camera.disconnect()


async def test_camera_exposure_can_be_cancelled(omnisim, tmp_path):  # noqa: ANN001
    camera = await _connected(AlpacaCamera, omnisim, images_dir=tmp_path)
    try:
        task = asyncio.create_task(camera.expose(ExposureParams(duration=30)))
        await asyncio.sleep(1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await camera.get_status()).state == DeviceState.CONNECTED
        # The camera is free again.
        assert (await camera.expose(ExposureParams(duration=0.1))).width == 800
    finally:
        await camera.disconnect()


async def test_camera_status_and_cooler(omnisim, tmp_path):  # noqa: ANN001
    camera = await _connected(AlpacaCamera, omnisim, images_dir=tmp_path)
    try:
        status = await camera.get_status()
        assert status.temperature is not None
        await camera.set_cooler(True, -10.0)           # the simulator's cooler, if it has one
        assert await camera.get_pixel_size_um() == pytest.approx(5.6)
        # OmniSim's camera has no guide output.
        with pytest.raises(PulseGuideNotSupported):
            await camera.pulse_guide("N", 100)
    finally:
        await camera.set_cooler(False, None)
        await camera.disconnect()


# ---------------------------------------------------------------------------
# Mount
# ---------------------------------------------------------------------------

def _target(hour_angle: float, dec: float, lon: float) -> SkyCoord:
    """A J2000 position at *hour_angle* (hours, + = west) from the meridian now."""
    lst = local_sidereal_time_h(datetime.now(timezone.utc), lon)
    return SkyCoord(ra=((lst - hour_angle) % 24) * u.hourangle, dec=dec * u.deg, frame="icrs")


async def _mount(sim: OmniSim) -> AlpacaMount:
    mount = await _connected(AlpacaMount, sim)
    if (await mount.get_status()).is_parked:
        await mount.unpark()
    return mount


async def _site_lon(mount: AlpacaMount) -> float:
    return float(await mount._alpaca.get("sitelongitude"))


async def test_mount_slews_to_a_j2000_position(omnisim):  # noqa: ANN001
    mount = await _mount(omnisim)
    try:
        target = _target(1.0, 40.0, await _site_lon(mount))
        await mount.slew(target)
        status = await mount.get_status()
        assert not status.is_slewing and status.is_tracking
        here = SkyCoord(ra=status.ra * u.hourangle, dec=status.dec * u.deg, frame="icrs")
        assert here.separation(target).arcsec < 60
        # JNow is what the mount itself reports: precessed, so not the J2000 numbers.
        assert abs(status.ra_jnow - status.ra) > 0.001
        assert status.hour_angle == pytest.approx(1.0, abs=0.05)
        assert status.pier_side in ("East", "West")
        assert status.alt is not None and status.az is not None
    finally:
        await mount.disconnect()


async def test_mount_sync_moves_its_idea_of_the_position(omnisim):  # noqa: ANN001
    mount = await _mount(omnisim)
    try:
        lon = await _site_lon(mount)
        await mount.slew(_target(0.5, 20.0, lon))
        synced = _target(0.5, 21.0, lon)
        await mount.sync(synced)
        status = await mount.get_status()
        here = SkyCoord(ra=status.ra * u.hourangle, dec=status.dec * u.deg, frame="icrs")
        assert here.separation(synced).arcsec < 60
    finally:
        await mount.disconnect()


async def test_mount_tracking_on_and_off(omnisim):  # noqa: ANN001
    mount = await _mount(omnisim)
    try:
        await mount.set_tracking(True, TrackingMode.LUNAR)
        assert (await mount.get_status()).is_tracking
        assert await mount._alpaca.get("trackingrate") == 1
        await mount.set_tracking(False)
        assert not (await mount.get_status()).is_tracking
        await mount.set_tracking(True, TrackingMode.SIDEREAL)
    finally:
        await mount.disconnect()


async def test_mount_parks_and_slewing_unparks_it(omnisim):  # noqa: ANN001
    mount = await _mount(omnisim)
    try:
        await mount.park()
        assert (await mount.get_status()).is_parked
        # A slew from park unparks first (a parked mount refuses to slew).
        await mount.slew(_target(-1.0, 30.0, await _site_lon(mount)))
        status = await mount.get_status()
        assert not status.is_parked and not status.is_slewing
    finally:
        await mount.disconnect()


@pytest.mark.parametrize("hour_angle", [2.0, -2.0])   # both sides of the pier
async def test_mount_nudges_the_right_way(omnisim, hour_angle):  # noqa: ANN001
    mount = await _mount(omnisim)
    try:
        await mount.slew(_target(hour_angle, 30.0, await _site_lon(mount)))
        for direction, axis, sign in (("N", "dec", 1), ("S", "dec", -1), ("E", "ra", 1), ("W", "ra", -1)):
            before = await mount.get_status()
            await mount.start_move(direction, "64x")
            await asyncio.sleep(1.0)
            await mount.stop_move()
            after = await mount.get_status()
            if axis == "dec":
                moved = after.dec - before.dec
            else:
                moved = ((after.ra - before.ra + 12) % 24 - 12) * 15
            assert moved * sign > 0.05, (direction, before.pier_side, moved)
        with pytest.raises(ValueError):
            await mount.start_move("N", "fast please")
    finally:
        await mount.stop_move()
        await mount.disconnect()


async def test_mount_pulse_guides(omnisim):  # noqa: ANN001
    mount = await _mount(omnisim)
    try:
        await mount.slew(_target(1.0, 10.0, await _site_lon(mount)))
        before = await mount.get_status()
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await mount.pulse_guide("N", 1000)
        assert loop.time() - t0 >= 0.95                # returns when the pulse is over
        after = await mount.get_status()
        assert (after.dec - before.dec) * 3600 > 5     # guide rate × 1 s, northwards
    finally:
        await mount.disconnect()


async def test_mount_meridian_flip_completes(omnisim):  # noqa: ANN001
    mount = await _mount(omnisim)
    try:
        target = _target(0.2, 25.0, await _site_lon(mount))
        await mount.slew(target)
        await mount.meridian_flip()
        status = await mount.get_status()
        assert not status.is_slewing
        here = SkyCoord(ra=status.ra * u.hourangle, dec=status.dec * u.deg, frame="icrs")
        assert here.separation(target).arcsec < 120     # still on the target
    finally:
        await mount.disconnect()


async def test_mount_pushes_its_position(omnisim):  # noqa: ANN001
    mount = await _mount(omnisim)
    calls: list[tuple] = []
    try:
        mount.set_coords_listener(lambda *args: calls.append(args))
        await asyncio.sleep(1.5)
        assert calls
        ra, dec, ra_jnow, dec_jnow, alt, az, pier, ha, lst, tracking, parked = calls[-1]
        assert None not in (ra, dec, ra_jnow, dec_jnow, lst)
    finally:
        await mount.disconnect()
    count = len(calls)
    await asyncio.sleep(1.5)
    assert len(calls) == count                         # stopped with the connection


async def test_mount_takes_the_site_and_time(omnisim):  # noqa: ANN001
    mount = await _mount(omnisim)
    a = mount._alpaca
    original = (await a.get("sitelatitude"), await a.get("sitelongitude"), await a.get("siteelevation"))
    try:
        await mount.set_location(48.85, 2.35, 35.0)
        assert await a.get("sitelatitude") == pytest.approx(48.85)
        assert await a.get("sitelongitude") == pytest.approx(2.35)
        await mount.set_time_utc()
    finally:
        await mount.set_location(*original)
        await mount.disconnect()


# ---------------------------------------------------------------------------
# Focuser, filter wheel, rotator, cover calibrator
# ---------------------------------------------------------------------------

async def test_focuser_moves(omnisim):  # noqa: ANN001
    focuser = await _connected(AlpacaFocuser, omnisim)
    try:
        await focuser.move_to(20000)
        status = await focuser.get_status()
        assert (status.position, status.is_moving) == (20000, False)
        await focuser.move_by(-500)
        assert (await focuser.get_status()).position == 19500
        assert (await focuser.get_status()).temperature is not None
        with pytest.raises(ValueError):
            await focuser.move_to(10**9)
        await focuser.halt()
    finally:
        await focuser.disconnect()


async def test_filter_wheel_changes_filters(omnisim):  # noqa: ANN001
    wheel = await _connected(AlpacaFilterWheel, omnisim)
    try:
        status = await wheel.get_status()
        assert status.filter_names[:3] == ["Red", "Green", "Blue"]
        assert status.filter_count == len(status.filter_names)
        await wheel.select_filter(3)
        status = await wheel.get_status()
        assert (status.current_slot, status.is_moving) == (3, False)
        await wheel.select_filter(1)
        assert (await wheel.get_status()).current_slot == 1
        with pytest.raises(ValueError):
            await wheel.select_filter(99)
    finally:
        await wheel.disconnect()


async def test_rotator_reports_its_angle(omnisim):  # noqa: ANN001
    rotator = await _connected(AlpacaRotator, omnisim)
    try:
        status = await rotator.get_status()
        assert status.state == DeviceState.CONNECTED and status.position is not None
    finally:
        await rotator.disconnect()


async def test_flat_panel_cover_and_light(omnisim):  # noqa: ANN001
    panel = await _connected(AlpacaFlatPanel, omnisim)
    try:
        status = await panel.get_status()
        assert status.has_cover and status.has_light and status.max_brightness == 100
        await panel.open_cover()
        assert (await panel.get_status()).cover == CoverState.OPEN
        await panel.set_light(True, 40)
        status = await panel.get_status()
        assert (status.light_on, status.brightness) == (True, 40)
        await panel.set_light(False)
        assert (await panel.get_status()).light_on is False
        with pytest.raises(ValueError):
            await panel.set_light(True, 500)
        await panel.close_cover()
        assert (await panel.get_status()).cover == CoverState.CLOSED
    finally:
        await panel.disconnect()


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

async def test_ping_and_disconnect(omnisim):  # noqa: ANN001
    focuser = await _connected(AlpacaFocuser, omnisim)
    assert await focuser.ping()
    await focuser.disconnect()
    assert (await focuser.get_status()).state == DeviceState.DISCONNECTED


async def test_a_missing_device_fails_to_connect(omnisim):  # noqa: ANN001
    camera = AlpacaCamera(host=omnisim.host, port=omnisim.port, device_number=7)
    with pytest.raises(AlpacaError):
        await camera.connect()
    assert (await camera.get_status()).state == DeviceState.ERROR


async def test_an_unreachable_server_fails_to_connect() -> None:
    client = AlpacaClient("127.0.0.1", 1, "focuser", 0, timeout=2.0)
    with pytest.raises(AlpacaError, match="unreachable"):
        await AlpacaFocuser(client=client).connect()
