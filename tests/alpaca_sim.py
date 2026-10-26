"""A throwaway ASCOM Alpaca simulator (OmniSim) for the integration tests.

OmniSim simulates one device of every kind (camera, telescope, focuser, filter wheel, rotator,
cover calibrator, …) behind the Alpaca REST API. It is found as ``ascom.alpaca.simulators`` on
the PATH, or at ``ASTROLOL_ALPACA_SIM``; the tests that need it are skipped without it.

It refuses to start while another process of the same name runs (it opens a browser on that
one instead), so it is started through a link of its own name: a developer's OmniSim keeps
running untouched. It keeps its settings under ``$HOME``, so it gets an empty one. One instance
serves the whole session; its devices keep their state from one test to the next.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

BINARY = "ascom.alpaca.simulators"


def omnisim_binary() -> str | None:
    found = os.environ.get("ASTROLOL_ALPACA_SIM") or shutil.which(BINARY)
    return os.path.realpath(found) if found and os.path.exists(found) else None


@dataclass
class OmniSim:
    host: str
    port: int
    process: subprocess.Popen

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_omnisim() -> tuple[OmniSim, Path]:
    binary = omnisim_binary()
    if binary is None:
        pytest.skip("OmniSim (ascom.alpaca.simulators) not installed")
    home = Path(tempfile.mkdtemp(prefix="omnisim-"))
    link = home / "astrolol-omnisim"
    link.symlink_to(binary)
    port = _free_port()
    proc = subprocess.Popen(
        [str(link), f"--urls=http://127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "HOME": str(home)},
        cwd=home,
    )
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            shutil.rmtree(home, ignore_errors=True)
            pytest.skip(f"OmniSim exited at start (rc={proc.returncode})")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/management/apiversions", timeout=1.0).status_code == 200:
                return OmniSim("127.0.0.1", port, proc), home
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    proc.kill()
    shutil.rmtree(home, ignore_errors=True)
    pytest.skip("OmniSim did not answer within 30 s")


def stop_omnisim(sim: OmniSim, home: Path) -> None:
    sim.process.terminate()
    try:
        sim.process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        sim.process.kill()
        sim.process.wait()
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture(scope="session")
def omnisim() -> Iterator[OmniSim]:
    sim, home = start_omnisim()
    yield sim
    stop_omnisim(sim, home)
