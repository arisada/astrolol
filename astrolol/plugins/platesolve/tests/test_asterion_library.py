"""AsterionSolver through the ``asterion`` Python package, against a stand-in for the package."""
import json
import types

import numpy as np
import pytest
from astropy.io import fits

from astrolol.plugins.platesolve import backends
from astrolol.plugins.platesolve.backends import AsterionSolver
from astrolol.plugins.platesolve.models import SolveRequest

_SOLVED = {
    "solved": True, "stars": 40, "ra": 35.18, "dec": 57.0, "fieldWidth": 0.5, "fieldHeight": 0.4,
    "wcs": {"CD1_1": -0.0004, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": 0.0004},
}


class _AsterionError(Exception):
    pass


class _FakeResult:
    def __init__(self, data) -> None:
        self.json = json.dumps(data)


class _FakeLibrary(types.SimpleNamespace):
    """What ``import asterion`` gives: records its solvers, solves, installs and closes."""

    def __init__(self, answer=_SOLVED) -> None:
        super().__init__(AsterionError=_AsterionError, answer=answer, opened=[], solves=[], installs=[], closed=0)
        lib = self

        class Solver:
            def __init__(self, directory) -> None:
                lib.opened.append(directory)

            def solve(self, pixels, **options):
                lib.solves.append((pixels, options))
                if isinstance(lib.answer, Exception):
                    raise lib.answer
                return _FakeResult(lib.answer)

            def close(self) -> None:
                lib.closed += 1

        self.Solver = Solver

    def install_catalog(self, name, directory, progress) -> None:
        self.installs.append((name, directory))
        if isinstance(self.answer, Exception):
            raise self.answer
        for p in (
            types.SimpleNamespace(event="step", step="Downloading tycho2", fraction=None, message=None),
            types.SimpleNamespace(event="progress", step="Downloading tycho2", fraction=0.5, message=None),
            types.SimpleNamespace(event="progress", step="Downloading tycho2", fraction=0.51, message=None),
            types.SimpleNamespace(event="done", step=None, fraction=1.0, message=None),
        ):
            progress(p)


@pytest.fixture
def lib(monkeypatch) -> _FakeLibrary:
    fake = _FakeLibrary()
    monkeypatch.setattr(backends, "_asterion_module", lambda: fake)
    return fake


def _fits(tmp_path, data) -> str:
    path = tmp_path / "f.fits"
    fits.PrimaryHDU(data).writeto(path)
    return str(path)


async def _noop(_: str) -> None:
    pass


@pytest.mark.asyncio
async def test_solves_with_the_library_and_keeps_the_solver_open(lib, tmp_path) -> None:
    path = _fits(tmp_path, np.arange(12, dtype=np.uint16).reshape(3, 4))
    solver = AsterionSolver("asterion", "/cats")
    req = SolveRequest(fits_path=path, ra_hint=35.0, dec_hint=57.0, radius=5.0, fov=0.5)
    result = await solver.solve(req, job_id="t", log=_noop)
    await solver.solve(req, job_id="t", log=_noop)
    assert (result.ra, result.dec) == (35.18, 57.0)
    assert lib.opened == ["/cats"]                         # opened once, for both solves
    pixels, options = lib.solves[0]
    assert pixels.dtype == np.dtype("=u2") and pixels.shape == (3, 4)
    assert options == {"ra": 35.0, "dec": 57.0, "radius": 5.0, "fov": 0.5}


@pytest.mark.asyncio
async def test_blind_when_only_one_coordinate_is_known(lib, tmp_path) -> None:
    path = _fits(tmp_path, np.zeros((3, 4), dtype=np.uint16))
    await AsterionSolver("asterion").solve(SolveRequest(fits_path=path, ra_hint=10.0), job_id="t", log=_noop)
    assert lib.solves[0][1] == {}


@pytest.mark.asyncio
async def test_pixels_are_converted_for_the_library(lib, tmp_path) -> None:
    solver = AsterionSolver("asterion")
    await solver.solve(SolveRequest(fits_path=_fits(tmp_path, np.zeros((3, 4), dtype=np.int32))), job_id="t", log=_noop)
    assert lib.solves[-1][0].dtype == np.float32
    colour = np.ones((3, 5, 4), dtype=np.uint8)            # channels first, as FITS stores them
    (tmp_path / "f.fits").unlink()
    await solver.solve(SolveRequest(fits_path=_fits(tmp_path, colour)), job_id="t", log=_noop)
    pixels = lib.solves[-1][0]
    assert pixels.shape == (5, 4) and float(pixels[0, 0]) == 3.0


@pytest.mark.asyncio
async def test_unsolved_and_library_errors_are_explained(lib, tmp_path) -> None:
    path = _fits(tmp_path, np.zeros((3, 4), dtype=np.uint16))
    req = SolveRequest(fits_path=path)
    lib.answer = {"solved": False, "stars": 12}
    with pytest.raises(RuntimeError, match=r"no solution found \(12 stars"):
        await AsterionSolver("asterion").solve(req, job_id="t", log=_noop)
    lib.answer = _AsterionError("No catalog is installed in /x")
    with pytest.raises(RuntimeError, match="Plate solve failed: No catalog is installed"):
        await AsterionSolver("asterion").solve(req, job_id="t", log=_noop)


@pytest.mark.asyncio
async def test_a_file_without_pixels_is_explained(lib, tmp_path) -> None:
    path = tmp_path / "empty.fits"
    fits.PrimaryHDU().writeto(path)
    with pytest.raises(RuntimeError, match="could not be read"):
        await AsterionSolver("asterion").solve(SolveRequest(fits_path=str(path)), job_id="t", log=_noop)


@pytest.mark.asyncio
async def test_without_the_package_the_program_is_used(monkeypatch) -> None:
    monkeypatch.setattr(backends, "_asterion_module", lambda: None)
    solver = AsterionSolver("__no_such_asterion__")
    assert not solver.uses_library and not solver.available()
    with pytest.raises(RuntimeError, match="not found"):
        await solver.solve(SolveRequest(fits_path="a.fits"), job_id="t", log=_noop)


def test_the_library_can_be_turned_off(lib) -> None:
    assert AsterionSolver("asterion").uses_library
    assert not AsterionSolver("__no_such_asterion__", library=False).uses_library
    assert AsterionSolver("__no_such_asterion__").available()      # the package alone is enough


@pytest.mark.asyncio
async def test_install_closes_the_solver_and_reports_progress(lib, tmp_path) -> None:
    solver = AsterionSolver("asterion", str(tmp_path / "cats"))
    await solver.solve(SolveRequest(fits_path=_fits(tmp_path, np.zeros((3, 4), dtype=np.uint16))), job_id="t", log=_noop)
    lines: list[str] = []

    async def log(msg: str) -> None:
        lines.append(msg)

    await solver.install_catalog(log)
    # the pending log calls are scheduled on the loop from the installing thread
    import asyncio
    await asyncio.sleep(0.05)
    assert lib.closed == 1 and lib.installs == [("tycho2", str(tmp_path / "cats"))]
    assert (tmp_path / "cats").is_dir()
    assert lines == ["Downloading tycho2", "Downloading tycho2 50%"]    # 51 % is the same tenth


@pytest.mark.asyncio
async def test_install_failure_is_a_runtime_error(lib, tmp_path) -> None:
    lib.answer = _AsterionError("no network")
    with pytest.raises(RuntimeError, match="no network"):
        await AsterionSolver("asterion", str(tmp_path / "c")).install_catalog(_noop)
