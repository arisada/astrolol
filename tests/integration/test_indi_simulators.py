"""
Integration tests against INDI simulator drivers.

Skipped automatically when indiserver is not installed.
Tests are async def — pytest-asyncio (asyncio_mode=auto) manages the loop.
All fixtures are async; the indipyclient backend is pure asyncio so no
synchronous workaround is needed.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("indiserver") is None,
    reason="indiserver not installed",
)

_BASE_PORT = 17600


def _start_indiserver(port: int, *drivers: str) -> subprocess.Popen:
    import socket
    # Use a unique socket path so this instance does not collide with a
    # running indiserver (which binds /tmp/indiserver by default) or with
    # the API integration test module which runs its own instance.
    socket_path = f"/tmp/indiserver_sim_{port}"
    proc = subprocess.Popen(
        ["indiserver", "-p", str(port), "-u", socket_path, *drivers],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Block until indiserver is accepting TCP connections (up to 5 s)
    deadline = time.monotonic() + 5.0
    connected = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.skip(
                f"indiserver exited immediately (rc={proc.returncode}, drivers={drivers})"
            )
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                connected = True
                break
        except OSError:
            time.sleep(0.2)
    if not connected:
        proc.kill()
        proc.wait()
        pytest.skip(f"indiserver did not open port {port} within 5 s (drivers={drivers})")
    time.sleep(0.3)  # extra margin for INDI protocol init
    if proc.poll() is not None:
        pytest.skip(
            f"indiserver crashed after bind (rc={proc.returncode}, drivers={drivers})"
        )
    return proc


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------------------
# IndiClient connectivity
# ---------------------------------------------------------------------------

async def test_client_connect_disconnect():
    from astrolol.devices.indi.client import IndiClient

    port = _BASE_PORT
    proc = _start_indiserver(port, "indi_simulator_telescope")
    try:
        client = IndiClient(host="localhost", port=port)
        await client.connect()
        await client.disconnect()
    finally:
        _stop(proc)


async def test_client_connect_fails_without_server():
    from astrolol.devices.indi.client import IndiClient

    client = IndiClient(host="localhost", port=_BASE_PORT + 99)
    with pytest.raises((ConnectionError, OSError)):
        await client.connect()


# ---------------------------------------------------------------------------
# Shared indiserver — one instance for all module-scoped device fixtures.
#
# indiserver binds a system-wide abstract Unix socket (@/tmp/indiserver)
# in addition to its TCP port, so only one indiserver can run per process
# at a time.  All three simulators are loaded into a single server so the
# module-scoped client fixtures can coexist.
# ---------------------------------------------------------------------------

_SHARED_PORT = _BASE_PORT + 10


@pytest.fixture(scope="module")
def _shared_server():
    proc = _start_indiserver(
        _SHARED_PORT,
        "indi_simulator_telescope",
        "indi_simulator_focus",
        "indi_simulator_ccd",
    )
    yield proc
    _stop(proc)


# ---------------------------------------------------------------------------
# Mount (Telescope Simulator)
# ---------------------------------------------------------------------------

@pytest.fixture
async def mount(_shared_server):
    from astrolol.devices.indi.client import IndiClient
    from astrolol.devices.indi.mount import IndiMount
    client = IndiClient(host="localhost", port=_SHARED_PORT)
    await client.connect()
    m = IndiMount(device_name="Telescope Simulator", client=client)
    await m.connect()
    yield m
    await m.disconnect()
    await client.disconnect()


async def test_mount_connect_state(mount):
    from astrolol.devices.base.models import DeviceState
    assert (await mount.get_status()).state == DeviceState.CONNECTED


async def test_mount_get_status_has_position(mount):
    status = await mount.get_status()
    assert status.ra is not None
    assert status.dec is not None


async def test_mount_slew(mount):
    from astrolol.devices.base.models import SlewTarget
    await mount.slew(SlewTarget(ra=2.0, dec=20.0))
    await asyncio.sleep(0.5)  # let position update propagate
    status = await mount.get_status()
    assert status.ra is not None
    assert abs(status.ra - 2.0) < 0.5


async def test_mount_set_tracking(mount):
    await mount.set_tracking(True)
    assert (await mount.get_status()).is_tracking is True


async def test_mount_stop_when_idle_safe(mount):
    await mount.stop()


async def test_mount_park_unpark(mount):
    await mount.park()
    assert (await mount.get_status()).is_parked is True
    await mount.unpark()
    assert (await mount.get_status()).is_parked is False


async def test_mount_ping(mount):
    assert await mount.ping() is True


# ---------------------------------------------------------------------------
# Focuser (Focuser Simulator)
# ---------------------------------------------------------------------------

@pytest.fixture
async def focuser(_shared_server):
    from astrolol.devices.indi.client import IndiClient
    from astrolol.devices.indi.focuser import IndiFocuser
    client = IndiClient(host="localhost", port=_SHARED_PORT)
    await client.connect()
    f = IndiFocuser(device_name="Focuser Simulator", client=client)
    await f.connect()
    yield f
    await f.disconnect()
    await client.disconnect()


async def test_focuser_connect_state(focuser):
    from astrolol.devices.base.models import DeviceState
    assert (await focuser.get_status()).state == DeviceState.CONNECTED


async def test_focuser_get_status_has_position(focuser):
    assert (await focuser.get_status()).position is not None


async def test_focuser_move_to(focuser):
    await focuser.move_to(10000)
    status = await focuser.get_status()
    assert status.position == pytest.approx(10000, abs=200)


async def test_focuser_move_by_positive(focuser):
    await focuser.move_to(10000)
    await focuser.move_by(500)
    assert (await focuser.get_status()).position == pytest.approx(10500, abs=200)


async def test_focuser_move_by_negative(focuser):
    await focuser.move_to(10000)
    await focuser.move_by(-500)
    assert (await focuser.get_status()).position == pytest.approx(9500, abs=200)


async def test_focuser_ping(focuser):
    assert await focuser.ping() is True


# ---------------------------------------------------------------------------
# Camera (CCD Simulator)
# ---------------------------------------------------------------------------

@pytest.fixture
async def camera(_shared_server, tmp_path):
    from astrolol.devices.indi.client import IndiClient
    from astrolol.devices.indi.camera import IndiCamera
    client = IndiClient(host="localhost", port=_SHARED_PORT)
    await client.connect()
    cam = IndiCamera(
        device_name="CCD Simulator",
        client=client,
        images_dir=tmp_path / "images",
    )
    await cam.connect()
    yield cam
    await cam.disconnect()
    await client.disconnect()


async def test_camera_connect_state(camera):
    from astrolol.devices.base.models import DeviceState
    assert (await camera.get_status()).state == DeviceState.CONNECTED


async def test_camera_expose_returns_image(camera):
    from astrolol.devices.base.models import ExposureParams
    image = await camera.expose(ExposureParams(duration=0.1))
    assert image.fits_path.endswith(".fits")
    assert Path(image.fits_path).exists()
    assert Path(image.fits_path).stat().st_size > 0


async def test_camera_expose_fits_valid(camera):
    from astrolol.devices.base.models import ExposureParams
    from astropy.io import fits
    image = await camera.expose(ExposureParams(duration=0.1))
    with fits.open(image.fits_path) as hdul:
        assert len(hdul) > 0


async def test_camera_get_status_has_temperature(camera):
    assert (await camera.get_status()).temperature is not None


async def test_camera_ping(camera):
    assert await camera.ping() is True
