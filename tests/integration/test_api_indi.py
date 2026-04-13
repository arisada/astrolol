"""
End-to-end API integration tests: HTTP → FastAPI → INDI adapter → indiserver → simulator.

Skipped automatically when indiserver is not installed.
All device kinds share a single indiserver instance because indiserver binds a
global abstract Unix socket (@/tmp/indiserver) — only one instance can run per host.

The canonical scenario exercised by test_camera_full_workflow:
  1. GET  /devices/available           → indi_camera is listed
  2. POST /devices/connect             → connect CCD Simulator
  3. GET  /devices/connected           → device appears
  4. POST /imager/{id}/expose          → 2-second exposure, FITS file written
  5. DELETE /devices/connected/{id}    → clean disconnect
"""
from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import pytest
from httpx import ASGITransport, AsyncClient


async def _poll_until(
    client: AsyncClient,
    url: str,
    predicate: Callable[[dict[str, Any]], bool],
    timeout: float = 60.0,
    interval: float = 0.3,
) -> dict[str, Any]:
    """Poll *url* until *predicate(body)* is True or *timeout* seconds elapse."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(url)
        if r.status_code == 200 and predicate(r.json()):
            return r.json()
        await asyncio.sleep(interval)
    raise TimeoutError(f"Condition not met within {timeout}s at {url}")


async def _wait_move_done(
    client: AsyncClient,
    status_url: str,
    busy_timeout: float = 2.0,
    done_timeout: float = 60.0,
) -> dict[str, Any]:
    """Wait for a fire-and-forget move to start (go busy) then complete.

    Fire-and-forget endpoints return 202 before the background task has
    necessarily set state=busy.  Phase 1 waits up to *busy_timeout* seconds
    for the state to become "busy"; phase 2 waits until it is no longer busy.
    If the move is so fast it was already done before phase 1 completes, phase
    2 just returns the final status immediately.
    """
    loop = asyncio.get_event_loop()
    # Phase 1: spin quickly until we see "busy" or give up
    deadline = loop.time() + busy_timeout
    while loop.time() < deadline:
        r = await client.get(status_url)
        if r.status_code == 200 and r.json().get("state") == "busy":
            break
        await asyncio.sleep(0.05)
    # Phase 2: wait until no longer busy
    return await _poll_until(client, status_url, lambda d: d["state"] != "busy", done_timeout)

pytestmark = pytest.mark.skipif(
    shutil.which("indiserver") is None,
    reason="indiserver not installed",
)

_BASE_PORT = 17700


# ---------------------------------------------------------------------------
# Helpers (identical contract to test_indi_simulators helpers)
# ---------------------------------------------------------------------------

def _start_indiserver(port: int, *drivers: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        ["indiserver", "-p", str(port), *drivers],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
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
        pytest.skip(f"indiserver did not open port {port} within 5s (drivers={drivers})")
    time.sleep(0.3)
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


def _make_unmanaged_app(port: int, images_dir: Path):
    """
    Create a FastAPI app wired to an already-running indiserver at *port*.

    Settings are mutated before app construction so IndiConnectionManager
    captures the right host/port/images_dir at instantiation time.
    """
    from astrolol.config.settings import settings
    from astrolol.main import create_app

    settings.indi_manage_server = False
    settings.indi_port = port
    settings.images_dir = images_dir
    return create_app()


# ---------------------------------------------------------------------------
# Shared indiserver — one instance for all three device types.
#
# indiserver binds a global abstract Unix socket (@/tmp/indiserver) in
# addition to its TCP port, so only one indiserver can run per host at a
# time.  All three simulators are loaded into a single server.
# ---------------------------------------------------------------------------

_SHARED_PORT = _BASE_PORT + 10


@pytest.fixture(scope="module")
def _shared_server():
    proc = _start_indiserver(
        _SHARED_PORT,
        "indi_simulator_ccd",
        "indi_simulator_telescope",
        "indi_simulator_focus",
    )
    yield _SHARED_PORT
    _stop(proc)


# ---------------------------------------------------------------------------
# Camera (CCD Simulator)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _cam_app(_shared_server, tmp_path_factory):
    images_dir = tmp_path_factory.mktemp("api_cam_images")
    return _make_unmanaged_app(_shared_server, images_dir)


@pytest.fixture
async def cam_client(_cam_app):
    async with AsyncClient(
        transport=ASGITransport(app=_cam_app),
        base_url="http://test",
        timeout=60.0,
    ) as c:
        yield c


@pytest.fixture
async def connected_cam(cam_client):
    r = await cam_client.post("/devices/connect", json={
        "device_id": "ccd1",
        "kind": "camera",
        "adapter_key": "indi_camera",
        "params": {"device_name": "CCD Simulator", "executable": ""},
    })
    assert r.status_code == 201, r.text
    yield cam_client
    await cam_client.delete("/devices/connected/ccd1")


async def test_camera_full_workflow(cam_client):
    """
    Canonical scenario: list → connect → expose 2 s → verify FITS → disconnect.
    """
    # 1. indi_camera must be in the available adapters
    r = await cam_client.get("/devices/available")
    assert r.status_code == 200
    assert "indi_camera" in r.json()["cameras"]

    # 2. Connect CCD Simulator (no driver executable needed — unmanaged mode)
    r = await cam_client.post("/devices/connect", json={
        "device_id": "ccd_wf",
        "kind": "camera",
        "adapter_key": "indi_camera",
        "params": {"device_name": "CCD Simulator", "executable": ""},
    })
    assert r.status_code == 201, r.text
    assert r.json()["device_id"] == "ccd_wf"

    # 3. Device appears in connected list
    r = await cam_client.get("/devices/connected")
    assert any(d["device_id"] == "ccd_wf" for d in r.json())

    # 4. Take a 2-second exposure
    r = await cam_client.post("/imager/ccd_wf/expose", json={"duration": 2.0})
    assert r.status_code == 201, r.text
    result = r.json()
    fits_path = Path(result["fits_path"])
    assert fits_path.suffix == ".fits"
    assert fits_path.exists()
    assert fits_path.stat().st_size > 0

    # 5. Disconnect
    r = await cam_client.delete("/devices/connected/ccd_wf")
    assert r.status_code == 204
    r = await cam_client.get("/devices/connected")
    assert not any(d["device_id"] == "ccd_wf" for d in r.json())


async def test_camera_expose_fits_valid(connected_cam):
    """FITS produced by a short exposure must be a parseable FITS file."""
    from astropy.io import fits

    r = await connected_cam.post("/imager/ccd1/expose", json={"duration": 0.1})
    assert r.status_code == 201, r.text
    with fits.open(r.json()["fits_path"]) as hdul:
        assert len(hdul) > 0
        assert hdul[0].data is not None


async def test_camera_status_after_expose(connected_cam):
    """ImagerManager tracks state; camera is IDLE after a completed exposure."""
    await connected_cam.post("/imager/ccd1/expose", json={"duration": 0.1})
    r = await connected_cam.get("/imager/ccd1/status")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"


async def test_camera_driver_catalog_lists_simulator(cam_client):
    """The catalog endpoint must list indi_simulator_ccd as a camera driver."""
    r = await cam_client.get("/indi/drivers/camera")
    assert r.status_code == 200
    executables = [d["executable"] for d in r.json()]
    assert "indi_simulator_ccd" in executables


async def test_camera_connect_unknown_device_fails(cam_client):
    """Connecting a device name that no loaded driver serves must return 502."""
    r = await cam_client.post("/devices/connect", json={
        "kind": "camera",
        "adapter_key": "indi_camera",
        "params": {"device_name": "No Such Device", "executable": ""},
    })
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# Mount (Telescope Simulator)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _mount_app(_shared_server, tmp_path_factory):
    images_dir = tmp_path_factory.mktemp("api_mount_images")
    return _make_unmanaged_app(_shared_server, images_dir)


@pytest.fixture
async def mount_client(_mount_app):
    async with AsyncClient(
        transport=ASGITransport(app=_mount_app),
        base_url="http://test",
        timeout=60.0,
    ) as c:
        yield c


@pytest.fixture
async def connected_mount(mount_client):
    r = await mount_client.post("/devices/connect", json={
        "device_id": "mount1",
        "kind": "mount",
        "adapter_key": "indi_mount",
        "params": {"device_name": "Telescope Simulator", "executable": ""},
    })
    assert r.status_code == 201, r.text
    yield mount_client
    await mount_client.delete("/devices/connected/mount1")


async def test_mount_status_has_position(connected_mount):
    r = await connected_mount.get("/mount/mount1/status")
    assert r.status_code == 200
    data = r.json()
    assert data["ra"] is not None
    assert data["dec"] is not None


async def test_mount_slew(connected_mount):
    # slew is fire-and-forget: 202 Accepted
    r = await connected_mount.post("/mount/mount1/slew", json={"ra": 3.0, "dec": 45.0})
    assert r.status_code == 202


async def test_mount_set_tracking(connected_mount):
    r = await connected_mount.post("/mount/mount1/tracking", json={"enabled": True})
    assert r.status_code == 204
    # The INDI server may take a moment to reflect the switch change; poll until confirmed.
    data = await _poll_until(
        connected_mount, "/mount/mount1/status", lambda d: d["is_tracking"] is True
    )
    assert data["is_tracking"] is True


async def test_mount_park_unpark(connected_mount):
    # park is fire-and-forget: 202 Accepted
    r = await connected_mount.post("/mount/mount1/park")
    assert r.status_code == 202
    data = await _poll_until(
        connected_mount, "/mount/mount1/status", lambda d: d["is_parked"] is True
    )
    assert data["is_parked"] is True

    r = await connected_mount.post("/mount/mount1/unpark")
    assert r.status_code == 204
    data = await _poll_until(
        connected_mount, "/mount/mount1/status", lambda d: d["is_parked"] is False
    )
    assert data["is_parked"] is False


async def test_mount_stop(connected_mount):
    r = await connected_mount.post("/mount/mount1/stop")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Focuser (Focuser Simulator)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _focuser_app(_shared_server, tmp_path_factory):
    images_dir = tmp_path_factory.mktemp("api_focuser_images")
    return _make_unmanaged_app(_shared_server, images_dir)


@pytest.fixture
async def focuser_client(_focuser_app):
    async with AsyncClient(
        transport=ASGITransport(app=_focuser_app),
        base_url="http://test",
        timeout=60.0,
    ) as c:
        yield c


@pytest.fixture
async def connected_focuser(focuser_client):
    r = await focuser_client.post("/devices/connect", json={
        "device_id": "foc1",
        "kind": "focuser",
        "adapter_key": "indi_focuser",
        "params": {"device_name": "Focuser Simulator", "executable": ""},
    })
    assert r.status_code == 201, r.text
    yield focuser_client
    await focuser_client.delete("/devices/connected/foc1")


async def test_focuser_status_has_position(connected_focuser):
    r = await connected_focuser.get("/focuser/foc1/status")
    assert r.status_code == 200
    assert r.json()["position"] is not None


async def test_focuser_move_to(connected_focuser):
    # move_to is fire-and-forget: 202 Accepted
    r = await connected_focuser.post("/focuser/foc1/move_to", json={"position": 10000})
    assert r.status_code == 202
    data = await _wait_move_done(connected_focuser, "/focuser/foc1/status")
    assert abs(data["position"] - 10000) < 200


async def test_focuser_move_by(connected_focuser):
    # move_to is async; wait for it to finish before issuing move_by (else 409 Conflict).
    await connected_focuser.post("/focuser/foc1/move_to", json={"position": 10000})
    await _wait_move_done(connected_focuser, "/focuser/foc1/status")
    r = await connected_focuser.post("/focuser/foc1/move_by", json={"steps": 500})
    assert r.status_code == 202
    data = await _wait_move_done(connected_focuser, "/focuser/foc1/status")
    assert abs(data["position"] - 10500) < 200


async def test_focuser_halt(connected_focuser):
    r = await connected_focuser.post("/focuser/foc1/halt")
    assert r.status_code == 204
