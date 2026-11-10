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
    manager = SolveManager(event_bus=bus, solvers=[fake])
    result = await manager.solve(fits_path="/tmp/a.fits", ra_hint=1.0)
    assert result.ra == 10.0
    assert fake.requests[0].ra_hint == 1.0
    assert any(getattr(e, "message", "") == "fake solver says hi" for e in bus.events)


@pytest.mark.asyncio
async def test_manager_defaults_to_astap() -> None:
    manager = SolveManager(event_bus=_Bus(), astap_bin="my_astap", astap_db_path="/db")
    solver = manager._solvers["astap"]
    assert isinstance(solver, AstapSolver)
    assert solver.program == "my_astap" and solver.db_path == "/db"
    await asyncio.sleep(0)


# ── Asterion ──────────────────────────────────────────────────────────────────

import json

from astrolol.plugins.platesolve.backends import AsterionSolver

_ASTERION_JSON = {
    "image": "a.fits", "solved": True, "stars": 531, "ra": 35.18, "dec": 57.005,
    "fieldWidth": 0.545, "fieldHeight": 0.436,
    "wcs": {"CD1_1": 4.2566e-4, "CD1_2": 1.6e-7, "CD2_1": 1.5e-7, "CD2_2": 4.2601e-4},
}


def test_asterion_command_carries_hints() -> None:
    req = SolveRequest(fits_path="/img/a.fits", ra_hint=150.0, dec_hint=-30.0, radius=5.0, fov=2.0, tolerance=0.01)
    cmd = AsterionSolver("asterion", "/cats").command(req)
    assert cmd[:2] == ["asterion", "--json"]
    assert cmd[cmd.index("--catalog-dir") + 1] == "/cats"
    assert cmd[cmd.index("--ra") + 1] == "150.0" and cmd[cmd.index("--dec") + 1] == "-30.0"
    assert cmd[cmd.index("--radius") + 1] == "5.0"
    assert cmd[cmd.index("--fov") + 1] == "2.0"
    assert "0.01" not in cmd                       # ASTAP's tolerance means nothing to it
    assert cmd[-1] == "/img/a.fits"                # read in place, not copied


def test_asterion_command_blind_needs_no_position() -> None:
    cmd = AsterionSolver("asterion").command(SolveRequest(fits_path="a.fits", ra_hint=10.0))
    assert "--ra" not in cmd and "--radius" not in cmd and "--catalog-dir" not in cmd


def test_asterion_parses_a_solution() -> None:
    r = AsterionSolver.parse_output(0, json.dumps(_ASTERION_JSON), "")
    assert (r.ra, r.dec) == (35.18, 57.005)
    assert r.pixel_scale == pytest.approx(1.5324, abs=1e-3)
    assert r.cd == (4.2566e-4, 1.6e-7, 1.5e-7, 4.2601e-4)
    assert r.field_w == 0.545 and r.field_h == 0.436
    assert r.rotation == pytest.approx(359.98, abs=0.01)   # same convention as ASTAP's parse


def test_asterion_unsolved_says_how_many_stars() -> None:
    out = json.dumps({"image": "a.fits", "solved": False, "stars": 4})
    with pytest.raises(RuntimeError, match=r"no solution found \(4 stars detected\)"):
        AsterionSolver.parse_output(1, out, "")


def test_asterion_accepts_a_list_and_reports_unreadable_images() -> None:
    assert AsterionSolver.parse_output(0, json.dumps([_ASTERION_JSON]), "").ra == 35.18
    with pytest.raises(RuntimeError, match="Unable to read"):
        AsterionSolver.parse_output(1, "[]", "a.fits: Unable to read a.fits")


def test_asterion_plain_text_errors_are_passed_on() -> None:
    with pytest.raises(RuntimeError, match="No catalog is installed"):
        AsterionSolver.parse_output(2, "No catalog is installed in /x. Install one with: asterion --download-catalog tycho2", "")


@pytest.mark.asyncio
async def test_asterion_missing_program() -> None:
    with pytest.raises(RuntimeError, match="not found"):
        await AsterionSolver("__no_such_asterion__").solve(SolveRequest(fits_path="a.fits"), job_id="x", log=_noop)


async def _noop(_: str) -> None:
    pass


# ── Choosing between solvers ─────────────────────────────────────────────────

class _Failing:
    name = "astap"

    async def solve(self, req, *, job_id, log):
        raise RuntimeError("astap found nothing")


class _App:
    """Just enough of app.state for the manager to read the platesolve settings."""

    def __init__(self, **settings) -> None:
        class _Store:
            def get_user_settings(_self):
                class _U:
                    plugin_settings = {"platesolve": settings}
                return _U()

        class _State:
            profile_store = _Store()

        self.state = _State()


def _manager(app_settings: dict, solvers) -> SolveManager:
    manager = SolveManager(event_bus=_Bus(), solvers=solvers)
    manager.attach_app(_App(**app_settings))
    return manager


@pytest.mark.asyncio
async def test_engine_setting_picks_the_solver() -> None:
    astap, other = _FakeSolver(), _FakeSolver()
    astap.name, other.name = "astap", "asterion"
    manager = _manager({"engine": "asterion"}, [astap, other])
    result = await manager.solve(fits_path="a.fits")
    assert result.solver == "asterion"
    assert other.requests and not astap.requests


@pytest.mark.asyncio
async def test_fallback_tries_the_other_solver() -> None:
    other = _FakeSolver()
    other.name = "asterion"
    result = await _manager({"engine": "astap", "fallback": True}, [_Failing(), other]).solve(fits_path="a.fits")
    assert result.solver == "asterion"


@pytest.mark.asyncio
async def test_no_fallback_reports_the_error() -> None:
    other = _FakeSolver()
    other.name = "asterion"
    manager = _manager({"engine": "astap", "fallback": False}, [_Failing(), other])
    with pytest.raises(RuntimeError, match="astap found nothing"):
        await manager.solve(fits_path="a.fits")
    assert not other.requests


@pytest.mark.asyncio
async def test_all_solvers_failing_reports_the_chosen_ones_error() -> None:
    class _Other(_Failing):
        name = "asterion"

        async def solve(self, req, *, job_id, log):
            raise RuntimeError("asterion found nothing")

    manager = _manager({"engine": "astap"}, [_Failing(), _Other()])
    with pytest.raises(RuntimeError, match="astap found nothing"):
        await manager.solve(fits_path="a.fits")
