"""Solver backends: the programs that turn a FITS file plus hints into a WCS solution.

SolveManager owns jobs, events and centering; a backend only solves one file. It works on a
private copy of the image (the manager hands it the path to read, never the capture itself),
reports progress through ``log`` and raises on failure. Cancellation is an
``asyncio.CancelledError`` the backend must turn into killing its subprocess.
"""
from __future__ import annotations

import asyncio
import json
import math
import shutil
import tempfile
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog

from astrolol.plugins.platesolve.models import SolveRequest, SolveResult

logger = structlog.get_logger()

LogFn = Callable[[str], Awaitable[None]]


@runtime_checkable
class Solver(Protocol):
    """One plate-solving program."""

    name: str

    async def solve(self, req: SolveRequest, *, job_id: str, log: LogFn) -> SolveResult:
        """Solve ``req.fits_path``. Raises RuntimeError with a readable message on failure."""
        ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _scale_and_rotation(cd: tuple[float, float, float, float]) -> tuple[float, float]:
    """(pixel scale in degrees, rotation in degrees north through east) of a CD matrix."""
    cd1_1, cd1_2, cd2_1, _ = cd
    return math.sqrt(cd1_1 ** 2 + cd2_1 ** 2), math.degrees(math.atan2(-cd1_2, cd1_1)) % 360


def parse_wcs(fits_path: str) -> SolveResult:
    """Read a WCS solution from a FITS header (blocking — run via asyncio.to_thread)."""
    import astropy.io.fits as afits

    with afits.open(fits_path) as hdul:
        h = hdul[0].header

        if "CRVAL1" not in h or "CRVAL2" not in h:
            raise RuntimeError("the solver returned success but WCS keywords are missing")

        ra = float(h["CRVAL1"])
        dec = float(h["CRVAL2"])

        cd: tuple[float, float, float, float] | None = None
        if "CD1_1" in h:
            cd = (
                float(h["CD1_1"]),
                float(h.get("CD1_2", 0)),
                float(h.get("CD2_1", 0)),
                float(h.get("CD2_2", 0)),
            )
            pixel_scale_deg, rotation = _scale_and_rotation(cd)
        else:
            pixel_scale_deg = abs(float(h.get("CDELT1", 0)))
            rotation = float(h.get("CROTA2", 0))

        pixel_scale = pixel_scale_deg * 3600  # arcsec/pixel
        naxis1 = int(h.get("NAXIS1", 0))
        naxis2 = int(h.get("NAXIS2", 0))
        field_w = naxis1 * pixel_scale_deg
        field_h = naxis2 * pixel_scale_deg

        return SolveResult(
            ra=round(ra, 6),
            dec=round(dec, 6),
            rotation=round(rotation, 2),
            pixel_scale=round(pixel_scale, 4),
            field_w=round(field_w, 4),
            field_h=round(field_h, 4),
            cd=cd,
        )


async def run_streaming(cmd: list[str], log: LogFn | None) -> tuple[int, str, str]:
    """Run ``cmd``, passing each stdout line to ``log`` (when given). Returns (returncode,
    stdout, stderr).

    The process is killed when the calling task is cancelled."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_lines: list[str] = []
    stderr_chunks: list[bytes] = []

    async def _drain_stderr() -> None:
        while True:
            chunk = await proc.stderr.read(4096)  # type: ignore[union-attr]
            if not chunk:
                break
            stderr_chunks.append(chunk)

    stderr_task = asyncio.create_task(_drain_stderr())
    try:
        while True:
            line = await proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                stdout_lines.append(text)
                if log is not None:
                    await log(text)
        await stderr_task
        await proc.wait()
    except asyncio.CancelledError:
        stderr_task.cancel()
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        raise

    stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
    return proc.returncode or 0, "\n".join(stdout_lines), stderr_text


# ---------------------------------------------------------------------------
# ASTAP
# ---------------------------------------------------------------------------

class AstapSolver:
    """ASTAP's command-line solver (``astap_cli``), which writes its solution into the FITS header."""

    name = "astap"

    def __init__(self, program: str = "astap_cli", db_path: str = "/opt/astap") -> None:
        self.program = program
        self.db_path = db_path

    def command(self, req: SolveRequest, fits: str) -> list[str]:
        cmd = [
            self.program,
            "-f", fits,
            "-z", "0",        # auto-downsample for speed
            "-r", str(req.radius),
            "-d", self.db_path,
            "-update",
        ]
        if req.ra_hint is not None:
            cmd += ["-ra", str(req.ra_hint / 15.0)]    # degrees → hours
        if req.dec_hint is not None:
            cmd += ["-spd", str(90.0 + req.dec_hint)]  # dec → south-pole distance
        if req.tolerance is not None:
            cmd += ["-t", str(req.tolerance)]
        if req.fov is not None:
            cmd += ["-fov", str(req.fov)]
        return cmd

    async def solve(self, req: SolveRequest, *, job_id: str, log: LogFn) -> SolveResult:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_fits = Path(tmpdir) / "solve.fits"
            await asyncio.to_thread(shutil.copy2, req.fits_path, str(tmp_fits))

            cmd = self.command(req, str(tmp_fits))
            logger.info("platesolve.running", solve_id=job_id, solver=self.name, cmd=" ".join(cmd))

            if not shutil.which(self.program):
                raise RuntimeError(
                    f"'{self.program}' not found — install the astap-cli package"
                )

            returncode, _, stderr = await run_streaming(cmd, log)
            if returncode != 0:
                raise RuntimeError(f"Plate solve failed: {stderr or f'exit code {returncode}'}")

            return await asyncio.to_thread(parse_wcs, str(tmp_fits))


# ---------------------------------------------------------------------------
# Asterion
# ---------------------------------------------------------------------------

def _asterion_module():
    """The ``asterion`` Python package (pip install asterion-solver), or None."""
    try:
        import asterion
    except ImportError:
        return None
    return asterion


def _load_pixels(fits_path: str):
    """The image of a FITS file as the gray levels Asterion reads (blocking)."""
    import astropy.io.fits as afits
    import numpy as np

    with afits.open(fits_path) as hdul:
        data = next((h.data for h in hdul if h.data is not None), None)
    if data is None:
        raise RuntimeError("the image could not be read: the FITS file has no pixels")
    if data.ndim == 3:  # a colour image: the sum of its channels, as the command line tool does
        data = data.sum(axis=0, dtype=np.float32)
    if data.ndim != 2:
        raise RuntimeError(f"the image could not be read: {data.ndim} dimensions")
    # FITS is big-endian; the library wants native order and 8/16-bit integers or 32-bit floats.
    if data.dtype.kind == "u" and data.dtype.itemsize <= 2:
        return data.astype(f"=u{data.dtype.itemsize}", copy=False)
    return data.astype(np.float32, copy=False)


class AsterionSolver:
    """The Asterion plate solver. It uses the ``asterion`` Python package when it is installed:
    the solver then stays in memory with its catalogs open between solves. Otherwise it runs the
    ``asterion`` program, which reads the image where it is and prints the solution as JSON."""

    name = "asterion"

    def __init__(self, program: str = "asterion", catalog_dir: str | None = None, *, library: bool = True) -> None:
        self.program = program
        self.catalog_dir = catalog_dir
        self._library = library
        self._open: object | None = None   # the library's Solver, opened by the first solve
        self._lock = threading.Lock()

    # The catalog the page installs: small enough for a Pi, for fields wider than 0.7°.
    DEFAULT_CATALOG = "tycho2"

    @property
    def uses_library(self) -> bool:
        return self._library and _asterion_module() is not None

    def available(self) -> bool:
        """Whether something can solve: the Python package, or the program on the PATH."""
        return self.uses_library or shutil.which(self.program) is not None

    def catalogs_installed(self) -> bool:
        return bool(self.catalog_dir) and any(Path(self.catalog_dir).glob("*.astx"))

    def download_command(self, catalog: str = DEFAULT_CATALOG) -> list[str]:
        cmd = [self.program]
        if self.catalog_dir:
            cmd += ["--catalog-dir", self.catalog_dir]
        return cmd + ["--download-catalog", catalog]

    def command(self, req: SolveRequest) -> list[str]:
        cmd = [self.program, "--json"]
        if self.catalog_dir:
            cmd += ["--catalog-dir", self.catalog_dir]
        # Position hints only mean something as a pair; without them the search is blind.
        if req.ra_hint is not None and req.dec_hint is not None:
            cmd += ["--ra", str(req.ra_hint), "--dec", str(req.dec_hint), "--radius", str(req.radius)]
        if req.fov is not None:
            cmd += ["--fov", str(req.fov)]
        # req.tolerance is ASTAP's match tolerance; Asterion verifies matches statistically.
        return cmd + [req.fits_path]

    def options(self, req: SolveRequest) -> dict[str, float]:
        """The same hints as ``command``, as options of the library's ``solve``."""
        opts: dict[str, float] = {}
        if req.ra_hint is not None and req.dec_hint is not None:
            opts.update(ra=req.ra_hint, dec=req.dec_hint, radius=req.radius)
        if req.fov is not None:
            opts["fov"] = req.fov
        return opts

    def close(self) -> None:
        """Release the catalogs held in memory; the next solve opens them again."""
        with self._lock:
            solver, self._open = self._open, None
        if solver is not None:
            solver.close()  # type: ignore[attr-defined]

    def _library_solver(self, asterion):
        with self._lock:
            if self._open is None:
                self._open = asterion.Solver(self.catalog_dir)
            return self._open

    def _solve_with_library(self, asterion, req: SolveRequest) -> SolveResult:
        """Blocking: run via asyncio.to_thread. A solve takes milliseconds, so one that is cancelled
        is left to finish rather than interrupted."""
        pixels = _load_pixels(req.fits_path)
        try:
            result = self._library_solver(asterion).solve(pixels, **self.options(req))
        except (asterion.AsterionError, ValueError) as exc:
            raise RuntimeError(f"Plate solve failed: {exc}") from None
        return self.result_from_data(json.loads(result.json))

    async def solve(self, req: SolveRequest, *, job_id: str, log: LogFn) -> SolveResult:
        asterion = _asterion_module() if self._library else None
        if asterion is not None:
            logger.info("platesolve.running", solve_id=job_id, solver=self.name, via="library")
            result = await asyncio.to_thread(self._solve_with_library, asterion, req)
        else:
            cmd = self.command(req)
            logger.info("platesolve.running", solve_id=job_id, solver=self.name, cmd=" ".join(cmd))
            if not shutil.which(self.program):
                raise RuntimeError(f"'{self.program}' not found — install the Asterion solver")
            returncode, stdout, stderr = await run_streaming(cmd, None)
            result = self.parse_output(returncode, stdout, stderr)
        await log(
            f"solved with Asterion: {result.ra:.4f} {result.dec:+.4f}, "
            f"{result.pixel_scale:.2f}\"/px"
        )
        return result

    async def install_catalog(self, log: LogFn) -> None:
        """Download the default catalog, reporting progress through ``log``. Raises RuntimeError."""
        if self.catalog_dir:
            Path(self.catalog_dir).mkdir(parents=True, exist_ok=True)
        asterion = _asterion_module() if self._library else None
        if asterion is None:
            code, _, stderr = await run_streaming(self.download_command(), log)
            if code != 0:
                raise RuntimeError(stderr or f"exit code {code}")
            return

        loop = asyncio.get_running_loop()
        last: list[object] = [None]

        def progress(p) -> None:  # runs on the installing thread
            # One line per step, then one per 10 % of it.
            mark = (p.step, int((p.fraction or 0) * 10))
            text = p.message or p.step
            if text and (p.event in ("detail", "info") or mark != last[0]):
                last[0] = mark
                suffix = f" {round(p.fraction * 100)}%" if p.event == "progress" and p.fraction is not None else ""
                asyncio.run_coroutine_threadsafe(log(f"{text}{suffix}"), loop)

        # The library asks for its solver to be closed before it installs the catalog again.
        await asyncio.to_thread(self.close)
        try:
            await asyncio.to_thread(asterion.install_catalog, self.DEFAULT_CATALOG, self.catalog_dir, progress)
        except asterion.AsterionError as exc:
            raise RuntimeError(str(exc)) from None

    @classmethod
    def parse_output(cls, returncode: int, stdout: str, stderr: str) -> SolveResult:
        """Turn the program's output into a result, or raise RuntimeError saying why not."""
        try:
            data = json.loads(stdout)
        except ValueError:
            # Errors that are not about one image (no catalog, bad option) are plain text.
            detail = (stderr or stdout).strip() or f"exit code {returncode}"
            raise RuntimeError(f"Plate solve failed: {detail}") from None
        if isinstance(data, list):
            if not data:  # the image could not be read; the reason is on stderr
                raise RuntimeError(f"Plate solve failed: {stderr.strip() or 'the image could not be read'}")
            data = data[0]
        return cls.result_from_data(data)

    @staticmethod
    def result_from_data(data: dict) -> SolveResult:
        """A result from Asterion's JSON for one image (the program's and the library's are the same)."""
        if not data.get("solved"):
            stars = data.get("stars")
            detail = f"no solution found ({stars} stars detected)" if stars is not None else "no solution found"
            raise RuntimeError(f"Plate solve failed: {detail}")

        wcs = data["wcs"]
        cd = (wcs["CD1_1"], wcs["CD1_2"], wcs["CD2_1"], wcs["CD2_2"])
        pixel_scale_deg, rotation = _scale_and_rotation(cd)
        return SolveResult(
            ra=round(float(data["ra"]), 6),
            dec=round(float(data["dec"]), 6),
            rotation=round(rotation, 2),
            pixel_scale=round(pixel_scale_deg * 3600, 4),
            field_w=round(float(data["fieldWidth"]), 4),
            field_h=round(float(data["fieldHeight"]), 4),
            cd=cd,
        )
