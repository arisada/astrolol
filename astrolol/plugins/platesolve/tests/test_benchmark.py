"""The solver benchmark: image preparation, hint extraction, and the report."""
import asyncio

import astropy.io.fits as afits
import numpy as np
import pytest

from astrolol.plugins.platesolve import benchmark as bm
from astrolol.plugins.platesolve.models import SolveRequest, SolveResult


def _result(ra: float, dec: float) -> SolveResult:
    return SolveResult(ra=ra, dec=dec, rotation=0.0, pixel_scale=1.0, field_w=1.0, field_h=1.0)


class _Solver:
    def __init__(self, name: str, answer=None, error: str | None = None, delay: float = 0.0) -> None:
        self.name, self.answer, self.error, self.delay = name, answer, error, delay
        self.requests: list[SolveRequest] = []

    async def solve(self, req, *, job_id, log):
        self.requests.append(req)
        await asyncio.sleep(self.delay)
        if self.error:
            raise RuntimeError(self.error)
        return self.answer


def _fits(path, **keys):
    hdu = afits.PrimaryHDU(np.full((64, 80), 1000, dtype=np.uint16))
    for k, v in keys.items():
        hdu.header[k] = v
    hdu.writeto(path)
    return path


def test_header_hints_from_ra_dec_and_optics() -> None:
    h = afits.Header({"RA": 35.18, "DEC": 57.0, "FOCALLEN": 700.0, "XPIXSZ": 5.2, "NAXIS2": 1024})
    ra, dec, fov = bm.header_hints(h)
    assert (ra, dec) == (35.18, 57.0)
    assert fov == pytest.approx(0.436, abs=0.001)


def test_header_hints_from_sexagesimal_object_position() -> None:
    h = afits.Header({"OBJCTRA": " 2 20 43.19", "OBJCTDEC": "-57 00 18.98"})
    ra, dec, fov = bm.header_hints(h)
    assert ra == pytest.approx(35.18, abs=0.001)
    assert dec == pytest.approx(-57.0053, abs=0.001)
    assert fov is None


def test_header_hints_missing() -> None:
    assert bm.header_hints(afits.Header()) == (None, None, None)


def test_blind_image_loses_every_position_keyword(tmp_path) -> None:
    src = _fits(tmp_path / "a.fits", RA=10.0, DEC=20.0, OBJCTRA="0 40 0", CRVAL1=10.0, CD1_1=1e-4, A_ORDER=2, A_0_2=1e-7, FOCALLEN=700.0)
    ra, dec, _ = bm.prepare_image(src, tmp_path / "b.fits", "blind", "original")
    assert ra is None and dec is None
    h = afits.getheader(tmp_path / "b.fits")
    for key in ("RA", "DEC", "OBJCTRA", "CRVAL1", "CD1_1", "A_ORDER", "A_0_2"):
        assert key not in h
    assert h["FOCALLEN"] == 700.0   # the scale stays: a blind solve still knows the optics


def test_hinted_image_keeps_the_position(tmp_path) -> None:
    src = _fits(tmp_path / "a.fits", RA=10.0, DEC=20.0)
    ra, dec, _ = bm.prepare_image(src, tmp_path / "b.fits", "hinted", "original")
    assert (ra, dec) == (10.0, 20.0)
    assert afits.getheader(tmp_path / "b.fits")["RA"] == 10.0


def test_crop_halves_the_image_and_the_field(tmp_path) -> None:
    src = _fits(tmp_path / "a.fits", RA=10.0, DEC=20.0, FOCALLEN=700.0, XPIXSZ=5.2)
    _, _, fov_full = bm.prepare_image(src, tmp_path / "full.fits", "hinted", "original")
    _, _, fov_crop = bm.prepare_image(src, tmp_path / "crop.fits", "hinted", "crop")
    assert afits.getdata(tmp_path / "crop.fits").shape == (32, 40)
    assert fov_crop == pytest.approx(fov_full / 2)


def test_noisy_image_differs_but_keeps_its_type(tmp_path) -> None:
    src = _fits(tmp_path / "a.fits")
    bm.prepare_image(src, tmp_path / "n.fits", "hinted", "noisy")
    data = afits.getdata(tmp_path / "n.fits")
    assert data.shape == (64, 80)
    assert data.min() >= 0 and data.max() <= 65535


def test_unknown_variant_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        bm.prepare_image(_fits(tmp_path / "a.fits"), tmp_path / "b.fits", "hinted", "bogus")


def test_find_images_walks_folders(tmp_path) -> None:
    (tmp_path / "night").mkdir()
    _fits(tmp_path / "night" / "a.fits")
    _fits(tmp_path / "b.FIT")
    (tmp_path / "notes.txt").write_text("x")
    assert [p.name for p in bm.find_images([str(tmp_path)])] == ["b.FIT", "a.fits"]
    with pytest.raises(FileNotFoundError):
        bm.find_images([str(tmp_path / "missing")])


def test_separation_arcsec() -> None:
    assert bm.separation_arcsec(_result(10.0, 0.0), _result(10.0, 1.0 / 3600)) == pytest.approx(1.0, abs=1e-6)
    assert bm.separation_arcsec(_result(10.0, 20.0), _result(10.0, 20.0)) == 0.0


@pytest.mark.asyncio
async def test_benchmark_runs_every_solver_and_reports(tmp_path) -> None:
    src = _fits(tmp_path / "a.fits", RA=10.0, DEC=20.0, FOCALLEN=700.0, XPIXSZ=5.2)
    fast = _Solver("fast", _result(10.0, 20.0))
    slow = _Solver("slow", _result(10.0, 20.0 + 2.0 / 3600), delay=0.01)
    broken = _Solver("broken", error="Plate solve failed: nothing")
    runs = await bm.benchmark([src], [fast, slow, broken], modes=["hinted", "blind"], variants=["original"], repeat=2)

    assert len(runs) == 6
    assert len(fast.requests) == 4            # two modes × two repeats
    hinted = [r for r in fast.requests if r.ra_hint is not None]
    blind = [r for r in fast.requests if r.ra_hint is None]
    assert len(hinted) == 2 and len(blind) == 2
    assert all(r.radius == 180.0 for r in blind) and all(r.radius == 30.0 for r in hinted)
    assert len(broken.requests) == 2          # a failure stops the repeats

    summary = bm.summarize(runs)
    rows = {(r["mode"], r["solver"]): r for r in summary["solvers"]}
    assert rows[("hinted", "fast")]["solved"] == 1
    assert rows[("hinted", "broken")]["solved"] == 0
    assert rows[("hinted", "slow")]["median_ms"] > rows[("hinted", "fast")]["median_ms"]
    pair = next(a for a in summary["agreement"] if (a["a"], a["b"], a["mode"]) == ("fast", "slow", "hinted"))
    assert pair["median_arcsec"] == pytest.approx(2.0, abs=1e-3)

    text = bm.format_report(runs)
    assert "fast" in text and "Failures:" in text and "nothing" in text
    assert bm.runs_to_json(runs)["summary"]["solvers"]


@pytest.mark.asyncio
async def test_a_solve_that_hangs_counts_as_failed(tmp_path) -> None:
    run = await bm.run_one(_Solver("stuck", _result(0, 0), delay=5.0), SolveRequest(fits_path="x"), repeat=3, timeout=0.05)
    assert not run.solved and "timeout" in (run.error or "")
    assert len(run.seconds) == 1


@pytest.mark.asyncio
async def test_unreadable_image_is_a_finding_not_a_crash(tmp_path) -> None:
    bad = tmp_path / "bad.fits"
    bad.write_text("not a fits file")
    runs = await bm.benchmark([bad], [_Solver("s", _result(0, 0))], modes=["hinted"], variants=["original"], repeat=1)
    assert len(runs) == 1 and "cannot prepare" in (runs[0].error or "")
