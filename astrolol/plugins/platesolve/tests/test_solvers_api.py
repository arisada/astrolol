"""GET /solvers and POST /install_catalog."""
import asyncio
import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.plugins.platesolve.api import router
from astrolol.plugins.platesolve.backends import AsterionSolver, AstapSolver
from astrolol.plugins.platesolve.solver import SolveManager


class _Bus:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def publish(self, event) -> None:
        self.messages.append(getattr(event, "message", ""))


def _client(solvers) -> tuple[TestClient, _Bus]:
    app = FastAPI()
    bus = _Bus()
    app.state.solve_manager = SolveManager(event_bus=bus, solvers=solvers)
    app.state.event_bus = bus
    app.include_router(router)
    return TestClient(app), bus


def test_solvers_reports_program_and_data(tmp_path) -> None:
    db = tmp_path / "db"
    db.mkdir()
    (db / "d05_0101.1476").write_text("x")
    cats = tmp_path / "cats"
    cats.mkdir()
    client, _ = _client([
        AstapSolver("__no_such_astap__", str(db)),
        AsterionSolver("python3", str(cats)),   # any program on the PATH
    ])
    by_name = {s["name"]: s for s in client.get("/plugins/platesolve/solvers").json()}
    assert by_name["astap"] == {
        "name": "astap", "program": "__no_such_astap__", "program_found": False,
        "data_path": str(db), "data_installed": True,
    }
    assert by_name["asterion"]["program_found"] is True
    assert by_name["asterion"]["data_installed"] is False
    (cats / "tycho2.astx").write_text("x")
    by_name = {s["name"]: s for s in client.get("/plugins/platesolve/solvers").json()}
    assert by_name["asterion"]["data_installed"] is True


def test_install_catalog_needs_the_program() -> None:
    client, _ = _client([AsterionSolver("__no_such_asterion__", "/nonexistent")])
    r = client.post("/plugins/platesolve/install_catalog")
    assert r.status_code == 409 and "not found" in r.json()["detail"]


def test_install_catalog_without_asterion_is_404() -> None:
    client, _ = _client([AstapSolver()])
    assert client.post("/plugins/platesolve/install_catalog").status_code == 404


def test_download_command_names_the_catalog_dir() -> None:
    cmd = AsterionSolver("asterion", "/cats").download_command()
    assert cmd == ["asterion", "--catalog-dir", "/cats", "--download-catalog", "tycho2"]


@pytest.mark.asyncio
async def test_install_catalog_runs_the_download_and_reports(tmp_path) -> None:
    from astrolol.plugins.platesolve.api import _do_install_catalog

    program = tmp_path / "fake_asterion"
    program.write_text('#!/bin/sh\necho "Downloading $4"\nmkdir -p "$2"\ntouch "$2/tycho2.astx"\n')
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    cats = tmp_path / "cats"
    solver = AsterionSolver(str(program), str(cats))
    bus = _Bus()
    await _do_install_catalog(bus, solver)
    assert solver.catalogs_installed()
    assert any("Downloading tycho2" in m for m in bus.messages)
    assert any("installed successfully" in m for m in bus.messages)


@pytest.mark.asyncio
async def test_install_catalog_failure_is_logged(tmp_path) -> None:
    from astrolol.plugins.platesolve.api import _do_install_catalog

    program = tmp_path / "failing"
    program.write_text("#!/bin/sh\necho no network >&2\nexit 3\n")
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    bus = _Bus()
    await _do_install_catalog(bus, AsterionSolver(str(program), str(tmp_path / "c")))
    assert any("Download failed: no network" in m for m in bus.messages)
    await asyncio.sleep(0)
