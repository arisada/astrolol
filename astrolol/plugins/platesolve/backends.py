"""Solver backends: the programs that turn a FITS file plus hints into a WCS solution.

SolveManager owns jobs, events and centering; a backend only solves one file. It works on a
private copy of the image (the manager hands it the path to read, never the capture itself),
reports progress through ``log`` and raises on failure. Cancellation is an
``asyncio.CancelledError`` the backend must turn into killing its subprocess.
"""
from __future__ import annotations

import asyncio
import math
import shutil
import tempfile
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
