"""Starting and stopping a throwaway indiserver for the integration tests.

INDI drivers read and write ``$HOME/.indi`` (saved driver configs, park data, scope configs),
so each server gets an empty home of its own, under the one the root conftest.py creates for
the whole session. A test therefore never sees state saved by an earlier test or by the
developer's own INDI sessions, and never writes into the developer's ``~/.indi``.

The same goes for INDIGO servers (``start_indigo_server``), which keep their state in
``$HOME/.indigo``; ``stop_indiserver`` stops either kind.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

# Set by the root conftest.py before anything else runs.
INDI_HOME_ENV = "ASTROLOL_TEST_INDI_HOME"

# What a simulator CCD needs to know about the telescope in front of it to size its field of
# view; INDI 2.x leaves both at 0 (no stars) where 1.9.x filled in defaults.
SCOPE_FOCAL_LENGTH_MM = 1000.0
SCOPE_APERTURE_MM = 200.0

_homes: dict[int, Path] = {}


def start_indiserver(port: int, *drivers: str) -> subprocess.Popen:
    """indiserver on *port* with *drivers*, in a fresh INDI home; skips the test if it won't start."""
    # A unique socket path, so this instance does not collide with a running indiserver
    # (which binds /tmp/indiserver by default) or another test module's.
    socket_path = f"/tmp/indiserver_test_{port}"
    return _start(["indiserver", "-p", str(port), "-u", socket_path, *drivers], port, drivers)


def start_indigo_server(port: int, *drivers: str) -> subprocess.Popen:
    """indigo_server on *port* with *drivers*, in a fresh home; skips the test if it won't start."""
    # By its real path, so it finds its driver list (<prefix>/share/indigo) and lists every
    # driver in Server.DRIVERS. -b-: no network announcement; -w- -c-: no web pages.
    server = os.path.realpath(shutil.which("indigo_server") or "indigo_server")
    return _start([server, "-p", str(port), "-b-", "-w-", "-c-", *drivers], port, drivers)


def _start(cmd: list[str], port: int, drivers: tuple[str, ...]) -> subprocess.Popen:
    server = Path(cmd[0]).name
    session_home = os.environ.get(INDI_HOME_ENV)
    home = Path(tempfile.mkdtemp(prefix=f"{server}-{port}-", dir=session_home))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "HOME": str(home)},
    )
    _homes[proc.pid] = home
    deadline = time.monotonic() + 5.0
    connected = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.skip(f"{server} exited immediately (rc={proc.returncode}, drivers={drivers})")
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                connected = True
                break
        except OSError:
            time.sleep(0.2)
    if not connected:
        proc.kill()
        proc.wait()
        pytest.skip(f"{server} did not open port {port} within 5 s (drivers={drivers})")
    time.sleep(0.1)  # brief margin for INDI protocol init
    if proc.poll() is not None:
        pytest.skip(f"{server} crashed after bind (rc={proc.returncode}, drivers={drivers})")
    return proc


def stop_indiserver(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    home = _homes.pop(proc.pid, None)
    if home is not None:
        shutil.rmtree(home, ignore_errors=True)


async def set_scope_info(client, device: str) -> None:
    """Give a simulator camera a telescope (focal length, aperture) to size its star field from."""
    await client.set_number(
        device, "SCOPE_INFO",
        {"FOCAL_LENGTH": SCOPE_FOCAL_LENGTH_MM, "APERTURE": SCOPE_APERTURE_MM},
    )
