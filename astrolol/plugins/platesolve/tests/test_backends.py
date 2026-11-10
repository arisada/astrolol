"""Solver backends: the protocol, ASTAP's command line and the manager's use of an injected backend."""
import asyncio

import pytest

from astrolol.plugins.platesolve.backends import AstapSolver, Solver
from astrolol.plugins.platesolve.models import SolveRequest, SolveResult
from astrolol.plugins.platesolve.solver import SolveManager

_RESULT = SolveResult(ra=10.0, dec=20.0, rotation=0.0, pixel_scale=1.0, field_w=1.0, field_h=1.0)


class _Bus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


class _FakeSolver:
    name = "fake"

    def __init__(self) -> None:
        self.requests: list[SolveRequest] = []

    async def solve(self, req, *, job_id, log):
        self.requests.append(req)
        await log("fake solver says hi")
        return _RESULT


def test_astap_solver_satisfies_protocol() -> None:
    assert isinstance(AstapSolver(), Solver)
    assert isinstance(_FakeSolver(), Solver)


def test_astap_command_carries_hints() -> None:
    req = SolveRequest(fits_path="x.fits", ra_hint=150.0, dec_hint=-30.0, radius=5.0, tolerance=0.01, fov=2.0)
    cmd = AstapSolver("astap_cli", "/db").command(req, "/tmp/solve.fits")
    assert cmd[:2] == ["astap_cli", "-f"]
    assert cmd[cmd.index("-ra") + 1] == "10.0"      # hours
    assert cmd[cmd.index("-spd") + 1] == "60.0"     # south-pole distance
    assert cmd[cmd.index("-r") + 1] == "5.0"
    assert cmd[cmd.index("-t") + 1] == "0.01"
    assert cmd[cmd.index("-fov") + 1] == "2.0"
    assert cmd[cmd.index("-d") + 1] == "/db"


def test_astap_command_without_hints_is_blind() -> None:
    cmd = AstapSolver().command(SolveRequest(fits_path="x.fits"), "/tmp/s.fits")
    assert "-ra" not in cmd and "-spd" not in cmd and "-fov" not in cmd and "-t" not in cmd


@pytest.mark.asyncio
async def test_manager_uses_injected_solver_and_forwards_its_log() -> None:
    bus, fake = _Bus(), _FakeSolver()
    manager = SolveManager(event_bus=bus, solver=fake)
    result = await manager.solve(fits_path="/tmp/a.fits", ra_hint=1.0)
    assert result.ra == 10.0
    assert fake.requests[0].ra_hint == 1.0
    assert any(getattr(e, "message", "") == "fake solver says hi" for e in bus.events)


@pytest.mark.asyncio
async def test_manager_defaults_to_astap() -> None:
    manager = SolveManager(event_bus=_Bus(), astap_bin="my_astap", astap_db_path="/db")
    assert isinstance(manager._solver, AstapSolver)
    assert manager._solver.program == "my_astap" and manager._solver.db_path == "/db"
    await asyncio.sleep(0)

