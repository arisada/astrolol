"""What stacking short frames costs: duty cycle and noise, against one native long exposure.

    python3 -m astrolol.plugins.stacked_camera.benchmark                  # INDI simulators
    python3 -m astrolol.plugins.stacked_camera.benchmark --host localhost --port 7624 \\
        --camera "ZWO CCD ASI183MM Pro" --total 60 --subs 1 5 10 --gain 120

Without --host it starts its own indiserver with the CCD and telescope simulators. Point a real
camera at a patch of sky (or cap it for a dark: noise only) and give it its INDI device name.

For each sub-exposure length it takes two stacked exposures of --total seconds, and two native
exposures of the same length for reference. The two frames of a pair are subtracted: what is left
is random noise only (fixed pattern, bias and the offset the stack adds up cancel), so the ratio
of the stack's noise to the native frame's is the price of stacking. Also reported:

  duty    exposure time collected / wall-clock time the exposure took (below 1: the camera needs
          time between frames, and that time is lost)
  flux    light of the brightest star in the stack, relative to the native frame, scaled by the
          exposure time actually collected (about 1.00 when stacking collects light correctly)

Modes: ``stream`` uses the camera's native stream when it has one; ``looping`` forces back-to-back
exposures, as for a camera that cannot stream.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import astropy.io.fits as astropy_fits
import numpy as np

from astrolol.core.events import EventBus
from astrolol.devices.base.models import ExposureParams
from astrolol.plugins.stacked_camera.adapters import bind_adapters
from astrolol.plugins.stacked_camera.hubs import HubRegistry

MODES = ("stream", "looping")
CAMERA_ID = "camera"
STAR_BOX = 12  # half-width of the box that collects a star's light, pixels


@dataclass
class Row:
    mode: str
    sub: float
    total: float
    exposure: float  # seconds of light in the stack
    wall: float  # seconds the exposure took
    duty: float
    subs: int
    dropped: int
    noise: float  # per-pixel noise of the stack, from the pair difference (ADU)
    noise_ratio: float  # against the native exposure
    flux_ratio: float  # star light against the native frame, per second of light


def pair_noise(a: np.ndarray, b: np.ndarray) -> float:
    """Random noise of one frame from two like frames: stars and gradients cancel, and a robust
    spread (MAD) keeps what is left of them out."""
    d = a.astype(np.float64) - b.astype(np.float64)
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2))


def brightest(frame: np.ndarray, half: int = STAR_BOX) -> tuple[int, int]:
    """(row, column) of the brightest patch's light, found on a box-smoothed copy so a hot pixel
    loses, then centred on the light inside the box (any box holding the star scores the same)."""
    data = frame.astype(np.float64)
    padded = np.pad(data, ((1, 0), (1, 0)))
    integral = padded.cumsum(0).cumsum(1)
    k = 2 * half + 1
    box = integral[k:, k:] - integral[:-k, k:] - integral[k:, :-k] + integral[:-k, :-k]
    top, left = np.unravel_index(int(np.argmax(box)), box.shape)
    light = np.clip(data[top : top + k, left : left + k] - np.median(data), 0, None)
    if light.sum() <= 0:
        return int(top) + half, int(left) + half
    rows, cols = np.indices(light.shape)
    return (
        int(round(top + float((rows * light).sum() / light.sum()))),
        int(round(left + float((cols * light).sum() / light.sum()))),
    )


def star_flux(frame: np.ndarray, centre: tuple[int, int], half: int = STAR_BOX) -> float:
    """Light in the box around *centre*, the frame's background taken off."""
    y, x = centre
    patch = frame[max(0, y - half) : y + half + 1, max(0, x - half) : x + half + 1]
    return float(patch.astype(np.float64).sum() - patch.size * np.median(frame))


class _Manager:
    """The one camera, as the device manager would hand it out."""

    def __init__(self, camera: object) -> None:
        self._camera = camera

    def get_camera(self, device_id: str) -> object:
        if device_id != CAMERA_ID:
            raise KeyError(device_id)
        return self._camera

    def get_config(self, device_id: str) -> Any:
        return SimpleNamespace(adapter_key="real", params={})

    def list_connected(self) -> list[dict[str, str]]:
        return [{"device_id": CAMERA_ID, "kind": "camera", "adapter_key": "real"}]


class _ExposeOnly:
    """A camera that cannot stream: only what ``ICamera`` has."""

    def __init__(self, camera: Any) -> None:
        self._camera = camera

    async def connect(self) -> None:
        await self._camera.connect()

    async def disconnect(self) -> None:
        await self._camera.disconnect()

    async def expose(self, params: ExposureParams) -> Any:
        return await self._camera.expose(params)

    async def abort(self) -> None:
        await self._camera.abort()

    async def get_status(self) -> Any:
        return await self._camera.get_status()

    async def set_cooler(self, enabled: bool, target_temperature: float | None) -> None:
        await self._camera.set_cooler(enabled, target_temperature)

    async def ping(self) -> bool:
        return bool(await self._camera.ping())


def _pixels(path: str) -> np.ndarray:
    return np.asarray(astropy_fits.getdata(path), dtype=np.float64)


async def _native(camera: Any, total: float, gain: int | None) -> tuple[np.ndarray, np.ndarray]:
    frames = []
    for _ in range(2):
        image = await camera.expose(ExposureParams(duration=total, gain=gain))
        frames.append(_pixels(image.fits_path))
    return frames[0], frames[1]


async def _stacked(
    camera: Any, mode: str, sub: float, total: float, gain: int | None, directory: Path
) -> tuple[Row, np.ndarray] | None:
    source = camera if mode == "stream" else _ExposeOnly(camera)
    if mode == "stream" and not getattr(camera, "can_stream", False):
        return None
    hubs = HubRegistry(_Manager(source), EventBus(), lambda: sub, frozenset())
    stacked_class, _ = bind_adapters(hubs, directory)
    stacked = stacked_class(source_id=CAMERA_ID)
    frames, exposure, walls, dropped, subs = [], 0.0, 0.0, 0, 0
    for _ in range(2):
        started = time.monotonic()
        image = await stacked.expose(ExposureParams(duration=total, gain=gain))
        walls += time.monotonic() - started
        header = astropy_fits.getheader(image.fits_path)
        exposure += image.exposure_duration
        dropped += int(header["NDROP"])
        subs += int(header["NSUBS"])
        frames.append(_pixels(image.fits_path))
    await hubs.shutdown()
    row = Row(
        mode=mode,
        sub=sub,
        total=total,
        exposure=exposure / 2,
        wall=walls / 2,
        duty=exposure / walls if walls else 0.0,
        subs=subs // 2,
        dropped=dropped,
        noise=pair_noise(frames[0], frames[1]),
        noise_ratio=0.0,
        flux_ratio=0.0,
    )
    return row, frames[0]


async def run(
    camera: Any,
    total: float,
    subs: list[float],
    modes: list[str],
    gain: int | None,
    directory: Path,
) -> list[Row]:
    print(f"native reference: 2 x {total:g} s ...", flush=True)
    a, b = await _native(camera, total, gain)
    native_noise = pair_noise(a, b)
    peak = a.max()
    if peak >= 32768 and int((a >= peak).sum()) >= 4:
        print(
            f"  warning: the native frame is clipped at {peak:.0f} ADU: its star flux is "
            "too low, so the flux ratio of the stacks reads above 1",
            flush=True,
        )
    centre = brightest(a)
    native_flux = star_flux(a, centre)
    print(
        f"  noise {native_noise:.2f} ADU, brightest star at (row, col) {centre}, "
        f"flux {native_flux:.0f} ADU",
        flush=True,
    )
    rows: list[Row] = []
    for mode in modes:
        for sub in subs:
            print(f"{mode}: {sub:g} s subs, 2 x {total:g} s ...", flush=True)
            result = await _stacked(camera, mode, sub, total, gain, directory)
            if result is None:
                print(f"  {mode}: the camera has no native stream, skipped", flush=True)
                break
            row, first = result
            row.noise_ratio = row.noise / native_noise if native_noise else float("nan")
            collected = row.exposure / total
            row.flux_ratio = (
                star_flux(first, centre) / (native_flux * collected)
                if native_flux and collected
                else float("nan")
            )
            rows.append(row)
            if row.noise == 0:
                print(
                    "  warning: the two stacks are identical: the stream delivers no real light "
                    "(a simulator's stream often does not)",
                    flush=True,
                )
            print(
                f"  duty {row.duty:.2f}, noise x{row.noise_ratio:.2f}, flux x{row.flux_ratio:.2f}",
                flush=True,
            )
    return rows


def print_table(rows: list[Row], native_noise_note: str = "") -> None:
    print()
    header = (
        f"{'mode':8} {'sub':>5} {'subs':>5} {'light s':>8} {'wall s':>7} {'duty':>5} "
        f"{'lost':>4} {'noise':>7} {'noise x':>8} {'flux x':>7}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r.mode:8} {r.sub:>5g} {r.subs:>5} {r.exposure:>8.1f} {r.wall:>7.1f} {r.duty:>5.2f} "
            f"{r.dropped:>4} {r.noise:>7.2f} {r.noise_ratio:>8.2f} {r.flux_ratio:>7.2f}"
        )
    if native_noise_note:
        print(native_noise_note)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return int(s.getsockname()[1])


async def _simulator(port: int) -> tuple[subprocess.Popen[bytes], Path]:
    home = Path(tempfile.mkdtemp(prefix="stackbench-"))
    proc = subprocess.Popen(
        [
            "indiserver",
            "-p",
            str(port),
            "-u",
            f"/tmp/indiserver_bench_{port}",
            "indi_simulator_ccd",
            "indi_simulator_telescope",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )
    for _ in range(50):
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                return proc, home
        except OSError:
            await asyncio.sleep(0.2)
    proc.kill()
    raise SystemExit("indiserver did not start")


async def main_async(args: argparse.Namespace) -> int:
    from astrolol.devices.indi.camera import IndiCamera
    from astrolol.devices.indi.client import IndiClient

    server: subprocess.Popen[bytes] | None = None
    home: Path | None = None
    host, port, name = args.host, args.port, args.camera
    simulated = host is None
    if simulated:
        if shutil.which("indiserver") is None:
            raise SystemExit("indiserver is not installed")
        port = _free_port()
        server, home = await _simulator(port)
        host, name = "localhost", name or "CCD Simulator"
    work = Path(tempfile.mkdtemp(prefix="stackbench-frames-"))
    client = IndiClient(host=host, port=port)
    await client.connect()
    camera = IndiCamera(name, client, images_dir=work)
    try:
        await camera.connect()
        if simulated:
            await client.set_number(name, "SCOPE_INFO", {"FOCAL_LENGTH": 1000.0, "APERTURE": 200.0})
            import astropy.units as u
            from astropy.coordinates import SkyCoord

            from astrolol.devices.indi.mount import IndiMount

            mount = IndiMount(device_name="Telescope Simulator", client=client)
            await mount.connect()
            await mount.slew(SkyCoord(ra=83.8 * u.deg, dec=-5.4 * u.deg))  # a rich field
            await asyncio.sleep(1)
            await client.wait_prop_not_busy(
                "Telescope Simulator", "EQUATORIAL_EOD_COORD", timeout=90
            )
        rows = await run(camera, args.total, args.subs, args.modes, args.gain, work)
    finally:
        await camera.disconnect()
        await client.disconnect()
        if server is not None:
            server.terminate()
            server.wait(timeout=5)
        for path in (home, work):
            if path is not None:
                shutil.rmtree(path, ignore_errors=True)
    print_table(rows)
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(r) for r in rows], indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--host", help="INDI server to use; default: start one with the simulators")
    p.add_argument("--port", type=int, default=7624)
    p.add_argument("--camera", help="INDI device name of the camera")
    p.add_argument(
        "--total", type=float, default=20.0, help="seconds of each exposure (default 20)"
    )
    p.add_argument(
        "--subs", type=float, nargs="+", default=[1.0, 2.0, 5.0], help="sub-exposure lengths"
    )
    p.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    p.add_argument("--gain", type=int)
    p.add_argument("--json", help="write the rows to this file")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
