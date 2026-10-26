"""The INDI mount proxy under an INDIGO server, as PHD2 would use it there.

An INDIGO server runs INDI drivers only from its start (-i), so the proxy is passed then and
the server started again when it is switched on or off. Skipped without indigo_server.
"""
from __future__ import annotations

import asyncio
import shutil
import threading
from http.server import ThreadingHTTPServer

import pytest

from astrolol.devices.indi.indigo import indi_driver_device
from astrolol.plugins.eqmod.astrolol_indi_mount_proxy import DEVICE
from astrolol.plugins.eqmod.indi_proxy_setup import write_launcher
from astrolol.plugins.eqmod.tests.test_indi_proxy import _StubApi

pytestmark = pytest.mark.skipif(shutil.which("indigo_server") is None, reason="indigo_server not installed")

_PORT = 17852


@pytest.fixture
def api():
    _StubApi.mount_connected = True
    _StubApi.mount_id = "m1"
    _StubApi.pulse_status = 204
    _StubApi.drop_after_response = False
    _StubApi.pulses = []
    _StubApi.pulse_targets = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
async def manager(tmp_path, monkeypatch):
    from astrolol.config.settings import settings
    from astrolol.devices.indi.plugin import IndiConnectionManager

    monkeypatch.setenv("HOME", str(tmp_path / "home"))   # indigo_server's ~/.indigo
    monkeypatch.setattr(settings, "indi_server_kind", "indigo")
    monkeypatch.setattr(settings, "indi_manage_server", True)
    monkeypatch.setattr(settings, "indi_port", _PORT)
    m = IndiConnectionManager(run_dir=tmp_path / "run")
    yield m
    await m.client.disconnect()
    await m.stop_server()


async def _wait_for(predicate, timeout: float = 10.0) -> None:  # noqa: ANN001
    for _ in range(int(timeout / 0.1)):
        if predicate():
            return
        await asyncio.sleep(0.1)
    raise TimeoutError


async def test_proxy_guides_through_an_indigo_server(api, manager, tmp_path):
    from astrolol.devices.indi.pulse import indi_pulse_guide

    launcher = str(write_launcher(tmp_path / "run", api))
    await manager.add_startup_driver(launcher)
    await manager.ensure_started()
    assert manager._server.runs(launcher)

    # What PHD2 lists: INDIGO names an INDI driver's device after the driver.
    device = indi_driver_device(DEVICE, launcher)
    assert device == "astrolol Mount Proxy @ astrolol-indi-mount-proxy"
    client = manager.client
    await client.connect_device(device)
    await indi_pulse_guide(client, device, "N", 120)
    assert [(d, ms) for d, ms, _t in _StubApi.pulses] == [("N", 120)]


async def test_switching_the_proxy_starts_the_server_again(api, manager, tmp_path):
    launcher = str(write_launcher(tmp_path / "run", api))
    await manager.ensure_started()
    first_pid = manager._server._managed_pid
    assert not manager._server.runs(launcher)

    await manager.add_startup_driver(launcher)    # no device connected: restarts now
    assert manager._server.runs(launcher)
    assert manager._server._managed_pid != first_pid
    await manager.client.wait_for_property(indi_driver_device(DEVICE, launcher), "CONNECTION", timeout=10.0)

    await manager.remove_startup_driver(launcher)
    assert not manager._server.runs(launcher)
    await _wait_for(lambda: manager._server.is_running)


async def test_a_running_device_holds_the_change_back(api, manager, tmp_path):
    launcher = str(write_launcher(tmp_path / "run", api))
    await manager.acquire()                       # a device is using the server
    pid = manager._server._managed_pid
    await manager.add_startup_driver(launcher)
    assert manager._server._managed_pid == pid
    assert not manager._server.runs(launcher)
    await manager.release()
