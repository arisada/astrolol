"""End-to-end with the real Asterion, by its Python package and by its program, and, when ASTAP
is installed too, a comparison.

Needs an installed catalog (``ASTROLOL_ASTERION_CATALOGS``, default ~/.astrolol/asterion). Each way
of running it is skipped when it is missing: ``pip install asterion-solver`` for the package,
``asterion`` on the PATH (or ``ASTROLOL_ASTERION``) for the program.
"""
import bz2
import os
import shutil
from pathlib import Path

import pytest

from astrolol.plugins.platesolve import benchmark as bm
from astrolol.plugins.platesolve.backends import AsterionSolver, AstapSolver, _asterion_module
from astrolol.plugins.platesolve.models import SolveRequest

_PROGRAM = os.environ.get("ASTROLOL_ASTERION", "asterion")
_CATALOGS = Path(os.environ.get("ASTROLOL_ASTERION_CATALOGS", Path.home() / ".astrolol" / "asterion"))
_TEST_FITS_BZ2 = Path(__file__).parent / "test.fits.bz2"

pytestmark = pytest.mark.skipif(not any(_CATALOGS.glob("*.astx")), reason=f"no Asterion catalog in {_CATALOGS}")


@pytest.fixture(params=["library", "program"])
def make(request):
    """Builds a solver that runs Asterion the way the parameter says."""
    if request.param == "library":
        if _asterion_module() is None:
            pytest.skip("asterion Python package not installed")
    elif shutil.which(_PROGRAM) is None:
        pytest.skip("asterion program not installed")

    def build(catalogs=_CATALOGS) -> AsterionSolver:
        return AsterionSolver(_PROGRAM, str(catalogs), library=request.param == "library")

    return build


async def _log(_: str) -> None:
    pass


@pytest.fixture
def frame(tmp_path) -> Path:
    path = tmp_path / "test.fits"
    path.write_bytes(bz2.decompress(_TEST_FITS_BZ2.read_bytes()))
    return path


@pytest.mark.asyncio
async def test_solves_blind_and_with_hints(frame, make) -> None:
    solver = make()
    blind = await solver.solve(SolveRequest(fits_path=str(frame)), job_id="t", log=_log)
    assert abs(blind.ra - 35.18) < 0.05 and abs(blind.dec - 57.005) < 0.05
    hinted = await solver.solve(
        SolveRequest(fits_path=str(frame), ra_hint=35.0, dec_hint=57.0, radius=5.0, fov=0.45), job_id="t", log=_log
    )
    assert bm.separation_arcsec(blind, hinted) < 1.0
    assert blind.cd is not None and abs(blind.pixel_scale - 1.53) < 0.02


@pytest.mark.asyncio
async def test_hints_far_from_the_sky_find_nothing(frame, make) -> None:
    solver = make()
    with pytest.raises(RuntimeError, match="no solution"):
        await solver.solve(
            SolveRequest(fits_path=str(frame), ra_hint=200.0, dec_hint=-20.0, radius=3.0), job_id="t", log=_log
        )


@pytest.mark.asyncio
async def test_missing_catalog_is_explained(frame, tmp_path, make) -> None:
    with pytest.raises(RuntimeError, match="catalog"):
        await make(tmp_path / "none").solve(SolveRequest(fits_path=str(frame)), job_id="t", log=_log)


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("astap_cli") is None or not Path("/opt/astap").is_dir(), reason="astap not installed")
async def test_agrees_with_astap(frame, make) -> None:
    req = SolveRequest(fits_path=str(frame), ra_hint=35.18, dec_hint=57.005, radius=30.0)
    ours = await make().solve(req, job_id="t", log=_log)
    theirs = await AstapSolver("astap_cli", "/opt/astap").solve(req, job_id="t", log=_log)
    assert bm.separation_arcsec(ours, theirs) < 2.0
    assert abs(ours.pixel_scale - theirs.pixel_scale) < 0.01
    # Same handedness: a mirrored image must not turn up as an unmirrored one.
    assert (ours.cd[0] * ours.cd[3] - ours.cd[1] * ours.cd[2] > 0) == (theirs.cd[0] * theirs.cd[3] - theirs.cd[1] * theirs.cd[2] > 0)
