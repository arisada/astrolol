"""Compare plate solvers on a set of images: how many they solve, how fast, and whether they agree.

    python3 -m astrolol.plugins.platesolve.benchmark ~/images/*.fits
    python3 -m astrolol.plugins.platesolve.benchmark ~/images --modes blind --variants original,crop,noisy \\
        --repeat 5 --json report.json

The solvers are the ones astrolol uses (``backends.py``), configured like the server is
(``astap_program``, ``asterion_program``, ... in the configuration file or ``ASTROLOL_*``
variables), so the numbers include the work the server does around the program itself.

Modes:
  hinted  position and field of view taken from the image header, as when the mount reports where it points
  blind   position and any existing solution removed from the image: the solver has to find the sky alone

Variants (stress the solver a bit more than a clean frame does):
  original  the image as it is
  crop      its central quarter (half the width and height)
  noisy     the image with extra noise, twice its own background noise
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from astrolol.plugins.platesolve.backends import AsterionSolver, AstapSolver, Solver
from astrolol.plugins.platesolve.models import SolveRequest, SolveResult

MODES = ("hinted", "blind")
VARIANTS = ("original", "crop", "noisy")
_FITS_SUFFIXES = {".fits", ".fit", ".fts"}

# Header keywords that tell a solver where the image is; removed for blind runs.
_POSITION_KEYS = (
    "RA", "DEC", "OBJCTRA", "OBJCTDEC", "OBJCTALT", "OBJCTAZ", "CRVAL1", "CRVAL2", "CRPIX1",
    "CRPIX2", "CDELT1", "CDELT2", "CROTA1", "CROTA2", "CTYPE1", "CTYPE2", "CUNIT1", "CUNIT2",
    "PC1_1", "PC1_2", "PC2_1", "PC2_2", "CD1_1", "CD1_2", "CD2_1", "CD2_2", "EQUINOX",
    "RADESYS", "WCSAXES", "PLTSOLVD", "LONPOLE", "LATPOLE", "A_ORDER", "B_ORDER", "AP_ORDER",
    "BP_ORDER", "SECPIX", "SECPIX1", "SECPIX2", "PIXSCALE", "SCALE",
)
_SIP_KEY = re.compile(r"^(A|B|AP|BP)_\d+_\d+$")


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def find_images(paths: list[str]) -> list[Path]:
    """FITS files named on the command line, or found (recursively) in the folders named."""
    found: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            found += sorted(f for f in p.rglob("*") if f.suffix.lower() in _FITS_SUFFIXES)
        elif p.is_file():
            found.append(p)
        else:
            raise FileNotFoundError(raw)
    return found


def _sexagesimal(text: str) -> float:
    parts = [float(x) for x in re.split(r"[\s:]+", text.strip()) if x]
    sign = -1.0 if text.strip().startswith("-") else 1.0
    value = abs(parts[0]) + (parts[1] / 60 if len(parts) > 1 else 0) + (parts[2] / 3600 if len(parts) > 2 else 0)
    return sign * value


def header_hints(header: Any) -> tuple[float | None, float | None, float | None]:
    """(ra°, dec°, field height°) as the header gives them; None where it does not say."""
    ra = dec = fov = None
    try:
        if "RA" in header and "DEC" in header:
            ra, dec = float(header["RA"]), float(header["DEC"])
        elif "OBJCTRA" in header and "OBJCTDEC" in header:
            ra, dec = _sexagesimal(str(header["OBJCTRA"])) * 15.0, _sexagesimal(str(header["OBJCTDEC"]))
        elif "CRVAL1" in header and "CRVAL2" in header:
            ra, dec = float(header["CRVAL1"]), float(header["CRVAL2"])
    except (ValueError, TypeError):
        ra = dec = None

    naxis2 = header.get("NAXIS2")
    try:
        if "FOCALLEN" in header and "XPIXSZ" in header and naxis2:
            binning = float(header.get("YBINNING", header.get("XBINNING", 1)))
            height_mm = float(header["XPIXSZ"]) * binning * float(naxis2) / 1000.0
            fov = math.degrees(2 * math.atan(height_mm / (2 * float(header["FOCALLEN"]))))
        elif "CD2_2" in header and naxis2:
            fov = math.hypot(float(header["CD2_2"]), float(header.get("CD1_2", 0))) * float(naxis2)
    except (ValueError, TypeError, ZeroDivisionError):
        fov = None
    return ra, dec, fov


def prepare_image(src: Path, dst: Path, mode: str, variant: str) -> tuple[float | None, float | None, float | None]:
    """Write the image to solve for this mode and variant to ``dst`` and return the hints
    (ra°, dec°, fov°) the solvers are given. Blocking."""
    import astropy.io.fits as afits
    import numpy as np

    with afits.open(src) as hdul:
        hdu = next((h for h in hdul if h.data is not None and h.data.ndim >= 2), None)
        if hdu is None:
            raise ValueError(f"{src}: no image data")
        header = hdu.header.copy()
        data = np.asarray(hdu.data)

    ra, dec, fov = header_hints(header)

    if variant == "crop":
        h, w = data.shape[-2:]
        data = data[..., h // 4: h - h // 4, w // 4: w - w // 4]
        if fov is not None:
            fov /= 2
    elif variant == "noisy":
        flat = data.astype(np.float64)
        median = float(np.median(flat))
        sigma = float(1.4826 * np.median(np.abs(flat - median)))
        noise = np.random.default_rng(0).normal(0.0, 2 * max(sigma, 1.0), data.shape)
        info = np.iinfo(data.dtype) if np.issubdtype(data.dtype, np.integer) else None
        noisy = flat + noise
        data = np.clip(noisy, info.min, info.max).astype(data.dtype) if info else noisy.astype(data.dtype)
    elif variant != "original":
        raise ValueError(f"unknown variant {variant!r}")

    for key in list(header.keys()):
        if key in ("NAXIS1", "NAXIS2", "NAXIS3"):
            del header[key]
    if mode == "blind":
        for key in list(header.keys()):
            if key in _POSITION_KEYS or _SIP_KEY.match(key):
                del header[key]
        ra = dec = None
    elif mode != "hinted":
        raise ValueError(f"unknown mode {mode!r}")

    afits.PrimaryHDU(data=data, header=header).writeto(dst, overwrite=True)
    return ra, dec, fov


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

@dataclass
class Run:
    image: str
    mode: str
    variant: str
    solver: str
    seconds: list[float] = field(default_factory=list)   # one per repeat
    solved: bool = False
    error: str | None = None
    result: SolveResult | None = None

    @property
    def median_s(self) -> float:
        return statistics.median(self.seconds) if self.seconds else math.nan


async def _noop(_: str) -> None:
    pass


async def run_one(solver: Solver, req: SolveRequest, repeat: int, timeout: float) -> Run:
    """Solve ``req`` ``repeat`` times with ``solver``. A failure or timeout stops the repeats."""
    run = Run(image=req.fits_path, mode="", variant="", solver=solver.name)
    for i in range(repeat):
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(solver.solve(req, job_id=f"bench{i}", log=_noop), timeout)
        except asyncio.TimeoutError:
            run.seconds.append(time.perf_counter() - t0)
            run.error = f"timeout after {timeout:g} s"
            return run
        except RuntimeError as exc:
            run.seconds.append(time.perf_counter() - t0)
            run.error = str(exc)
            return run
        run.seconds.append(time.perf_counter() - t0)
        run.solved, run.result = True, result
    return run


async def benchmark(
    images: list[Path],
    solvers: list[Solver],
    *,
    modes: list[str],
    variants: list[str],
    repeat: int = 3,
    timeout: float = 120.0,
    radius: float = 180.0,
    progress: Any = None,
) -> list[Run]:
    runs: list[Run] = []
    with tempfile.TemporaryDirectory(prefix="astrolol-bench-") as tmp:
        for image in images:
            for mode in modes:
                for variant in variants:
                    work = Path(tmp) / f"{image.stem}-{mode}-{variant}.fits"
                    try:
                        ra, dec, fov = await asyncio.to_thread(prepare_image, image, work, mode, variant)
                    except Exception as exc:  # an unreadable image is a finding, not a crash
                        for solver in solvers:
                            runs.append(Run(str(image), mode, variant, solver.name, error=f"cannot prepare image: {exc}"))
                        continue
                    req = SolveRequest(
                        fits_path=str(work), ra_hint=ra, dec_hint=dec, fov=fov,
                        radius=30.0 if mode == "hinted" else radius,
                    )
                    for solver in solvers:
                        run = await run_one(solver, req, repeat, timeout)
                        run.image, run.mode, run.variant = str(image), mode, variant
                        runs.append(run)
                        if progress:
                            progress(run)
                    work.unlink(missing_ok=True)
    return runs


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def separation_arcsec(a: SolveResult, b: SolveResult) -> float:
    """Angle between the two solutions' centres."""
    ra1, dec1, ra2, dec2 = map(math.radians, (a.ra, a.dec, b.ra, b.dec))
    s = math.sin((dec2 - dec1) / 2) ** 2 + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(s)))) * 3600


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def label(image: str) -> str:
    """``folder/file`` — file names alone repeat from one night's folder to the next."""
    p = Path(image)
    return f"{p.parent.name}/{p.name}" if p.parent.name else p.name


def _ms(seconds: float) -> str:
    return "-" if math.isnan(seconds) else f"{seconds * 1000:,.0f}"


def summarize(runs: list[Run]) -> dict[str, Any]:
    """Per (mode, variant, solver): solve rate and timing of the solved images; per (mode,
    variant) and pair of solvers: how far apart the solutions of images both solved are."""
    groups: dict[tuple[str, str, str], list[Run]] = {}
    for r in runs:
        groups.setdefault((r.mode, r.variant, r.solver), []).append(r)

    rows = []
    for (mode, variant, solver), rs in groups.items():
        times = [r.median_s for r in rs if r.solved]
        rows.append({
            "mode": mode, "variant": variant, "solver": solver,
            "images": len(rs), "solved": len(times),
            "median_ms": statistics.median(times) * 1000 if times else None,
            "p95_ms": _percentile(times, 0.95) * 1000 if times else None,
            "max_ms": max(times) * 1000 if times else None,
        })

    by_image: dict[tuple[str, str, str], dict[str, Run]] = {}
    for r in runs:
        by_image.setdefault((r.image, r.mode, r.variant), {})[r.solver] = r
    pairs: dict[tuple[str, str, str, str], list[float]] = {}
    only: dict[tuple[str, str, str], list[str]] = {}
    for (image, mode, variant), rs in by_image.items():
        names = sorted(rs)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ra, rb = rs[a], rs[b]
                if ra.solved and rb.solved:
                    pairs.setdefault((mode, variant, a, b), []).append(separation_arcsec(ra.result, rb.result))  # type: ignore[arg-type]
                elif ra.solved != rb.solved:
                    winner = a if ra.solved else b
                    only.setdefault((mode, variant, winner), []).append(label(image))
    agreement = [
        {"mode": m, "variant": v, "a": a, "b": b, "images": len(d),
         "median_arcsec": statistics.median(d), "max_arcsec": max(d)}
        for (m, v, a, b), d in pairs.items()
    ]
    return {
        "solvers": rows,
        "agreement": agreement,
        "only_one_solved": [{"mode": m, "variant": v, "solver": s, "images": names} for (m, v, s), names in only.items()],
    }


def format_report(runs: list[Run]) -> str:
    summary = summarize(runs)
    out = ["", f"{'mode':<7} {'variant':<9} {'solver':<9} {'solved':>9} {'median ms':>10} {'p95 ms':>8} {'max ms':>8}"]
    for r in summary["solvers"]:
        out.append(
            f"{r['mode']:<7} {r['variant']:<9} {r['solver']:<9} {r['solved']:>4}/{r['images']:<4} "
            f"{_ms((r['median_ms'] or math.nan) / 1000):>10} {_ms((r['p95_ms'] or math.nan) / 1000):>8} "
            f"{_ms((r['max_ms'] or math.nan) / 1000):>8}"
        )
    if summary["agreement"]:
        out += ["", "Where two solvers both solved an image, how far apart their centres are:"]
        for a in summary["agreement"]:
            out.append(
                f"  {a['mode']}/{a['variant']}: {a['a']} vs {a['b']} on {a['images']} images: "
                f"median {a['median_arcsec']:.2f}\", worst {a['max_arcsec']:.2f}\""
            )
    for o in summary["only_one_solved"]:
        out.append(f"  {o['mode']}/{o['variant']}: only {o['solver']} solved {', '.join(o['images'])}")
    failures = [r for r in runs if not r.solved]
    if failures:
        out += ["", "Failures:"]
        out += [f"  {label(r.image)} {r.mode}/{r.variant} {r.solver}: {r.error}" for r in failures]
    return "\n".join(out)


def runs_to_json(runs: list[Run]) -> dict[str, Any]:
    return {
        "runs": [
            {**{k: v for k, v in asdict(r).items() if k != "result"},
             "median_s": None if math.isnan(r.median_s) else r.median_s,
             "result": r.result.model_dump() if r.result else None}
            for r in runs
        ],
        "summary": summarize(runs),
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _csv(value: str, allowed: tuple[str, ...], what: str) -> list[str]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    bad = [i for i in items if i not in allowed]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown {what} {', '.join(bad)} (choose from {', '.join(allowed)})")
    return items


def main(argv: list[str] | None = None) -> int:
    from astrolol.config.settings import settings

    ap = argparse.ArgumentParser(prog="python3 -m astrolol.plugins.platesolve.benchmark", description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", help="FITS files, or folders searched for them")
    ap.add_argument("--solvers", default="astap,asterion", type=lambda v: _csv(v, ("astap", "asterion"), "solver"))
    ap.add_argument("--modes", default="hinted,blind", type=lambda v: _csv(v, MODES, "mode"))
    ap.add_argument("--variants", default="original", type=lambda v: _csv(v, VARIANTS, "variant"))
    ap.add_argument("--repeat", type=int, default=3, help="solves per image and solver, for the timing (default 3)")
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds before a solve counts as failed")
    ap.add_argument("--radius", type=float, default=180.0, help="search radius for blind runs, degrees")
    ap.add_argument("--json", metavar="FILE", help="write every run and the summary to FILE")
    ap.add_argument("--astap", default=settings.astap_program)
    ap.add_argument("--astap-db", default=str(settings.astap_database))
    ap.add_argument("--asterion", default=settings.asterion_program)
    ap.add_argument("--asterion-catalogs", default=str(settings.asterion_catalog_dir))
    args = ap.parse_args(argv)

    try:
        images = find_images(args.paths)
    except FileNotFoundError as exc:
        ap.error(f"no such file or folder: {exc}")
    if not images:
        ap.error("no FITS images found")
    available = {
        "astap": AstapSolver(args.astap, args.astap_db),
        "asterion": AsterionSolver(args.asterion, args.asterion_catalogs),
    }
    solvers = [available[name] for name in args.solvers]

    def progress(run: Run) -> None:
        state = f"{run.median_s * 1000:,.0f} ms" if run.solved else f"FAILED ({run.error})"
        print(f"  {label(run.image)} {run.mode}/{run.variant} {run.solver}: {state}", file=sys.stderr, flush=True)

    runs = asyncio.run(benchmark(
        images, solvers, modes=args.modes, variants=args.variants,
        repeat=max(1, args.repeat), timeout=args.timeout, radius=args.radius, progress=progress,
    ))
    print(format_report(runs))
    if args.json:
        Path(args.json).write_text(json.dumps(runs_to_json(runs), indent=2))
        print(f"\nFull results in {args.json}")
    return 0 if all(r.solved for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
