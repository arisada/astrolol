"""
Integration tests: astrolol's INDI adapters against INDIGO simulator drivers.

An INDIGO server speaks the INDI 1.7 XML protocol to a client that does not ask for more,
and translates the common property names to their INDI counterparts, so the INDI adapters
drive INDIGO devices too. Where INDIGO does differ (its guide companion devices, its flat panel names, the empty BLOB
it sends when an exposure starts, no answer to a CONNECT it has nothing to do for), the
adapters handle it, and the tests below cover it.

Skipped automatically when indigo_server is not installed.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from tests.indi_server import start_indigo_server as _start_indigo_server
from tests.indi_server import stop_indiserver as _stop

pytestmark = pytest.mark.skipif(
    shutil.which("indigo_server") is None,
    reason="indigo_server not installed",
)

_PORT = 17800

# Device names published by the INDIGO simulator drivers. indigo_ccd_simulator also attaches
# the imager's filter wheel and focuser, and the guide camera's ST4 output, as devices of
# their own; indigo_mount_simulator does the same with the mount's guide input.
_MOUNT = "Mount Simulator"
_IMAGER = "CCD Imager Simulator"
_GUIDE_CAMERA = "CCD Guider Simulator"
_WHEEL = "CCD Imager Simulator (wheel)"
_FOCUSER = "CCD Imager Simulator (focuser)"
_ROTATOR = "Field Rotator Simulator"
_FLAT_PANEL = "Flat Panel Simulator"


@pytest.fixture(scope="module")
def _server():
    proc = _start_indigo_server(
        _PORT,
        "indigo_ccd_simulator",
        "indigo_mount_simulator",
        "indigo_rotator_simulator",
        "indigo_aux_simulator",
    )
    yield proc
    _stop(proc)


@pytest.fixture(scope="module")
async def client(_server):
    from astrolol.devices.indi.client import IndiClient
    c = IndiClient(host="localhost", port=_PORT)
    await c.connect()
    await c.wait_for_property(_FLAT_PANEL, "CONNECTION", timeout=10.0)
    yield c
    await c.disconnect()


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

async def test_devices_are_listed(client):
    devices = set(client.list_devices())
    assert {_MOUNT, _IMAGER, _GUIDE_CAMERA, _WHEEL, _FOCUSER, _ROTATOR, _FLAT_PANEL} <= devices


# ---------------------------------------------------------------------------
# Mount
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def mount(client):
    from astrolol.devices.indi.mount import IndiMount
    m = IndiMount(device_name=_MOUNT, client=client)
    await m.connect()
    await m.unpark()
    yield m
    await m.disconnect()


async def test_mount_connect_state(mount):
    from astrolol.devices.base.models import DeviceState
    assert (await mount.get_status()).state == DeviceState.CONNECTED


async def test_mount_get_status_has_position(mount):
    status = await mount.get_status()
    assert status.ra is not None
    assert status.dec is not None


async def test_mount_set_tracking(mount):
    await mount.set_tracking(True)
    assert (await mount.get_status()).is_tracking is True


async def test_mount_slew(mount):
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    status = await mount.get_status()
    target_ra = ((status.ra or 0.0) + 0.5) % 24
    target_dec = 45.0
    await mount.slew(SkyCoord(ra=target_ra * u.hourangle, dec=target_dec * u.deg, frame="icrs"))
    await asyncio.sleep(0.5)  # let position update propagate
    status = await mount.get_status()
    assert status.ra == pytest.approx(target_ra, abs=0.05)
    assert status.dec == pytest.approx(target_dec, abs=0.5)


async def test_mount_sync(mount):
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    status = await mount.get_status()
    await mount.sync(SkyCoord(ra=status.ra * u.hourangle, dec=status.dec * u.deg, frame="icrs"))


async def test_mount_stop_when_idle_safe(mount):
    await mount.stop()


async def test_mount_park_unpark(mount):
    await mount.park()
    assert (await mount.get_status()).is_parked is True
    await mount.unpark()
    assert (await mount.get_status()).is_parked is False


async def test_mount_tracking_rate(mount, client):
    # INDIGO's rate switch is TELESCOPE_TRACK_RATE (INDI: TELESCOPE_TRACK_MODE).
    from astrolol.devices.base.models import TrackingMode
    await mount.set_tracking(True, TrackingMode.LUNAR)
    await asyncio.sleep(0.5)
    assert client.get_switch_state_nowait(_MOUNT, "TELESCOPE_TRACK_RATE", "TRACK_LUNAR") is True
    await mount.set_tracking(True, TrackingMode.SIDEREAL)
    await asyncio.sleep(0.5)
    assert client.get_switch_state_nowait(_MOUNT, "TELESCOPE_TRACK_RATE", "TRACK_SIDEREAL") is True


async def test_mount_ping(mount):
    assert await mount.ping() is True


async def test_mount_pulse_guide(mount):
    await mount.pulse_guide("N", 200)


async def test_connect_device_already_connected(mount):
    from astrolol.devices.indi.client import IndiClient
    other = IndiClient(host="localhost", port=_PORT)
    await other.connect()
    try:
        await other.connect_device(_MOUNT, conn_timeout=5.0)
    finally:
        await other.disconnect()


# ---------------------------------------------------------------------------
# Focuser and filter wheel (both attached by the CCD simulator)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def focuser(client):
    from astrolol.devices.indi.focuser import IndiFocuser
    f = IndiFocuser(device_name=_FOCUSER, client=client)
    await f.connect()
    yield f
    await f.disconnect()


async def test_simulator_focuser_is_set_up_like_a_real_one(focuser, client):
    # In focus at a positive position, with a focus curve a few thousand steps wide.
    from astrolol.devices.indi.indigo import SIMULATOR_BLUR_SCALE, SIMULATOR_FOCUS_POSITION
    assert (await focuser.get_status()).position == SIMULATOR_FOCUS_POSITION
    assert await client.get_number(_FOCUSER, "FOCUSER_SETUP", "FOCUS") == 0
    assert await client.get_number(_FOCUSER, "FOCUSER_SETUP", "BLUR_SCALE") == SIMULATOR_BLUR_SCALE
    assert client.get_switch_state_nowait(_FOCUSER, "FOCUSER_ON_POSITION_SET", "GOTO") is True


async def test_reconnecting_the_simulator_focuser_leaves_it_alone(focuser, client):
    from astrolol.devices.indi.indigo import SIMULATOR_FOCUS_POSITION, setup_simulator_focuser
    await focuser.move_to(SIMULATOR_FOCUS_POSITION + 300)
    assert await setup_simulator_focuser(client, _FOCUSER) is False
    assert (await focuser.get_status()).position == pytest.approx(SIMULATOR_FOCUS_POSITION + 300, abs=5)


async def test_focuser_move_to(focuser):
    await focuser.move_to(11000)
    assert (await focuser.get_status()).position == pytest.approx(11000, abs=5)


async def test_focuser_move_by(focuser):
    await focuser.move_to(11000)
    await focuser.move_by(-200)
    assert (await focuser.get_status()).position == pytest.approx(10800, abs=5)


async def test_focuser_temperature(focuser):
    # INDIGO: FOCUSER_TEMPERATURE (INDI: FOCUS_TEMPERATURE).
    assert (await focuser.get_status()).temperature is not None


async def test_focuser_ping(focuser):
    assert await focuser.ping() is True


@pytest.fixture(scope="module")
async def wheel(client):
    from astrolol.devices.indi.filter_wheel import IndiFilterWheel
    w = IndiFilterWheel(device_name=_WHEEL, client=client)
    await w.connect()
    yield w
    await w.disconnect()


async def test_wheel_status_lists_filters(wheel):
    status = await wheel.get_status()
    assert status.filter_count == 5
    assert len(status.filter_names) == 5


async def test_wheel_select_filter(wheel):
    await wheel.select_filter(3)
    assert (await wheel.get_status()).current_slot == 3


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def camera(client, tmp_path_factory):
    from astrolol.devices.indi.camera import IndiCamera
    cam = IndiCamera(
        device_name=_IMAGER,
        client=client,
        images_dir=tmp_path_factory.mktemp("indigo_cam_images"),
    )
    await cam.connect()
    yield cam
    await cam.disconnect()


async def test_camera_status_has_temperature(camera):
    assert (await camera.get_status()).temperature is not None


async def test_camera_pixel_size(camera):
    assert await camera.get_pixel_size_um() == pytest.approx(5.2)


async def test_camera_cooler(camera):
    await camera.set_cooler(True, -10.0)
    await asyncio.sleep(0.5)
    assert (await camera.get_status()).cooler_on is True
    await camera.set_cooler(False, None)


async def test_camera_scope_info(camera, client):
    # INDIGO: CCD_LENS (INDI: SCOPE_INFO).
    await camera.push_scope_info(1000.0, 200.0)
    await asyncio.sleep(0.5)
    assert client.get_number_nowait(_IMAGER, "CCD_LENS", "FOCAL_LENGTH") == pytest.approx(1000.0)
    assert client.get_number_nowait(_IMAGER, "CCD_LENS", "APERTURE") == pytest.approx(200.0)


async def test_camera_ping(camera):
    assert await camera.ping() is True


async def test_camera_expose_returns_image(camera):
    from astropy.io import fits
    from astrolol.devices.base.models import ExposureParams
    image = await camera.expose(ExposureParams(duration=0.2))
    with fits.open(image.fits_path) as hdul:
        assert hdul[0].data.shape == (1200, 1600)


async def test_camera_local_upload_expose(camera, tmp_path_factory):
    """Local upload mode: the driver writes the file itself and reports its path."""
    from astrolol.devices.base.models import ExposureParams
    upload_dir = tmp_path_factory.mktemp("indigo_local_upload")
    await camera.set_upload_local(upload_dir)
    try:
        image = await camera.expose(ExposureParams(duration=0.2))
    finally:
        await camera.restore_upload_client()
    assert Path(image.fits_path).exists()
    assert Path(image.fits_path).stat().st_size > 0


@pytest.fixture(scope="module")
async def guide_camera(client, tmp_path_factory):
    from astrolol.devices.indi.camera import IndiCamera
    cam = IndiCamera(
        device_name=_GUIDE_CAMERA,
        client=client,
        images_dir=tmp_path_factory.mktemp("indigo_guide_images"),
    )
    await cam.connect()
    yield cam
    await cam.disconnect()


async def test_guide_camera_pulse_guide(guide_camera):
    await guide_camera.pulse_guide("E", 200)


# ---------------------------------------------------------------------------
# Rotator and flat panel
# ---------------------------------------------------------------------------

async def test_rotator_status(client):
    from astrolol.devices.indi.rotator import IndiRotator
    r = IndiRotator(device_name=_ROTATOR, client=client)
    await r.connect()
    try:
        assert (await r.get_status()).position is not None
    finally:
        await r.disconnect()


@pytest.fixture(scope="module")
async def flat_panel(client):
    from astrolol.devices.indi.flat_panel import IndiFlatPanel
    p = IndiFlatPanel(device_name=_FLAT_PANEL, client=client)
    await p.connect()
    yield p
    await p.disconnect()


async def test_flat_panel_brightness_is_read(flat_panel):
    # FLAT_LIGHT_INTENSITY is one of the names INDIGO and INDI share.
    assert (await flat_panel.get_status()).brightness is not None


async def test_flat_panel_has_light_and_cover(flat_panel):
    status = await flat_panel.get_status()
    assert status.has_light and status.has_cover


async def test_flat_panel_light_and_brightness(flat_panel):
    await flat_panel.set_light(True, 80)
    await asyncio.sleep(0.5)
    status = await flat_panel.get_status()
    assert status.light_on is True and status.brightness == 80
    await flat_panel.set_light(False)
    await asyncio.sleep(0.5)
    assert (await flat_panel.get_status()).light_on is False


async def test_flat_panel_cover(flat_panel):
    from astrolol.devices.base.models import CoverState
    await flat_panel.open_cover()
    assert (await flat_panel.get_status()).cover == CoverState.OPEN
    await flat_panel.close_cover()
    assert (await flat_panel.get_status()).cover == CoverState.CLOSED
