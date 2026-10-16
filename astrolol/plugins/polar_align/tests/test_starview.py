"""The live star view, end to end with a fake camera: a star moves in the stream as the
knobs are turned, and the view reports the remaining error and where the star has to go."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import astropy.io.fits as fits
import numpy as np
import pytest

from astrolol.devices.base.streaming import Frame, FrameBroadcaster, StreamParams
from astrolol.mount.sky import jnow_to_icrs
from astrolol.plugins.polar_align import starview as starview_module
from astrolol.plugins.polar_align import wizard as wizard_module
from astrolol.plugins.polar_align.solver import PoleOffset
from astrolol.plugins.polar_align.starview import StarView, StarViewRequest, _window_around
from astrolol.plugins.polar_align.tests.test_solver import (
    LATITUDE,
    WHEN,
    _MOUNT_RA_HOURS,
    _convergence_case,
)
from astrolol.plugins.polar_align.tests.test_wizard import _site_fixtures, _wait_until
from astrolol.plugins.polar_align.wizard import PolarAlignWizard, WizardPoint, WizardRequest, WizardRun

WIDTH, HEIGHT = 800, 600
ARCSEC = 1.0 / 3600.0
SCALE = 8.0  # arcsec per pixel
# North up, east left, in the usual FITS sense.
CD = (-SCALE * ARCSEC, 0.0, 0.0, SCALE * ARCSEC)
START = (400.0, 300.0)


def _frame_pixels(star_xy: tuple[float, float], width: int = WIDTH, height: int = HEIGHT,
                  x0: int = 0, y0: int = 0, seed: int = 1, amplitude: float = 4000.0, noise: float = 3.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[y0:y0 + height, x0:x0 + width]
    img = 200.0 + rng.normal(0.0, noise, size=(height, width))
    img += amplitude * np.exp(-((xs - star_xy[0]) ** 2 + (ys - star_xy[1]) ** 2) / (2 * 2.0**2))
    return img.astype(np.float32)


class FakeStreamCamera:
    """Streams frames with one star wherever the test puts it, honouring the window."""

    def __init__(self) -> None:
        self.star = START
        self.amplitude = 4000.0
        self.noise = 3.0
        self.params: StreamParams | None = None
        self.started = 0
        self._broadcaster = FrameBroadcaster()
        self._task: asyncio.Task[None] | None = None
        self.seq = 0

    def subscribe_frames(self):
        return self._broadcaster.subscribe()

    async def start_stream(self, params: StreamParams) -> None:
        self.params = params
        self.started += 1
        self._task = asyncio.create_task(self._run(params))

    async def stop_stream(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._broadcaster.end()

    async def _run(self, params: StreamParams) -> None:
        roi = params.roi
        while True:
            await asyncio.sleep(0.005)
            self.seq += 1
            x0, y0 = (roi.x, roi.y) if roi else (0, 0)
            w, h = (roi.width, roi.height) if roi else (WIDTH, HEIGHT)
            self._broadcaster.publish(Frame(
                pixels=_frame_pixels(self.star, w, h, x0, y0, seed=self.seq, amplitude=self.amplitude, noise=self.noise),
                seq=self.seq,
                timestamp=asyncio.get_event_loop().time(), exposure=params.exposure,
                binning=params.binning, origin=(x0, y0),
            ))

    async def glide(self, to: tuple[float, float], steps: int = 6) -> None:
        """Move the star in steps small enough to be followed from frame to frame."""
        x, y = self.star
        for i in range(1, steps + 1):
            self.star = (x + (to[0] - x) * i / steps, y + (to[1] - y) * i / steps)
            seq = self.seq
            await _wait_until(lambda: self.seq >= seq + 3)


class FakeImager:
    def __init__(self, path, star: tuple[float, float] = START) -> None:
        self.path = path
        self.star = star  # where the star is in the exposure; the stream may disagree a little

    async def expose(self, camera_id, req):
        fits.PrimaryHDU(_frame_pixels(self.star)).writeto(self.path, overwrite=True)
        return SimpleNamespace(fits_path=str(self.path))


class FakeMount:
    async def get_status(self, mount_id):
        return SimpleNamespace(ra_jnow=_MOUNT_RA_HOURS)


def _setup(tmp_path, monkeypatch, alt_err0: float, az_err0: float, d_az: float = 0.0, d_alt: float = 0.0,
           exposure_star: tuple[float, float] = START):
    """A converging run for a mount with the given error, the knob turn the user will make
    afterwards, and the pixel shift that turn gives the star."""
    monkeypatch.setattr(wizard_module, "_now", lambda: WHEN)
    monkeypatch.setattr(starview_module, "_now", lambda: WHEN)
    axis_ha, axis_dec, reference, new, exp_alt, exp_az = _convergence_case(alt_err0, az_err0, d_az, d_alt)

    profile, store = _site_fixtures(tmp_path, LATITUDE)
    camera = FakeStreamCamera()
    solve_icrs = jnow_to_icrs(reference.solved_ra_hours, reference.solved_dec_deg, WHEN)

    class Solver:
        async def solve(self, **kwargs):
            return SimpleNamespace(
                ra=float(solve_icrs.ra.deg), dec=float(solve_icrs.dec.deg), rotation=0.0, pixel_scale=SCALE,
                field_w=1.0, field_h=1.0, cd=CD,
            )

    app = SimpleNamespace(state=SimpleNamespace(
        mount_manager=FakeMount(), imager_manager=FakeImager(tmp_path / "f.fits", exposure_star), solve_manager=Solver(),
        device_manager=SimpleNamespace(get_camera=lambda _id: camera),
        active_profile=profile, equipment_store=store, profile_store=None,
    ))
    run = WizardRun(
        id="r", status="converging", request=WizardRequest(mount_id="m", camera_id="c", exposure_s=1.0, binning=1),
        started_at=WHEN,
        points=[WizardPoint(index=2, mount_ra_hours=_MOUNT_RA_HOURS, solved_ra_hours=reference.solved_ra_hours,
                            solved_dec_deg=reference.solved_dec_deg, when=WHEN)],
        result=PoleOffset(axis_ha_hours=axis_ha, axis_dec_deg=axis_dec, axis_ra_hours=0.0,
                          alt_error_arcmin=alt_err0, az_error_arcmin=az_err0),
    )
    # Where the star goes in the image when the pointing moves from the reference to `new`.
    cosd = np.cos(np.radians(reference.solved_dec_deg))
    xi = (new.solved_ra_hours - reference.solved_ra_hours) * 15.0 * cosd
    eta = new.solved_dec_deg - reference.solved_dec_deg
    cd = np.array([[CD[0], CD[1]], [CD[2], CD[3]]])
    shift = np.linalg.inv(cd) @ np.array([-xi, -eta])
    wizard = PolarAlignWizard(app, SimpleNamespace(publish=_async_noop))
    return StarView(app, wizard), run, camera, (START[0] + shift[0], START[1] + shift[1]), (exp_alt, exp_az)


async def _async_noop(*_a, **_k):
    return None


@pytest.mark.asyncio
async def test_reports_the_error_before_any_knob_is_turned(tmp_path, monkeypatch) -> None:
    view, run, camera, _moved, _expected = _setup(tmp_path, monkeypatch, 5.0, 4.0)
    await view.start(run, StarViewRequest(exposure_s=0.2))
    try:
        await _wait_until(lambda: view.info().state == "tracking")
        info = view.info()
        assert info.alt_error_arcmin == pytest.approx(5.0, abs=0.6)
        assert info.az_error_arcmin == pytest.approx(4.0, abs=0.6)
        assert info.star is not None and (info.star.x, info.star.y) == pytest.approx(START, abs=1.0)
        assert info.target is not None and info.az_via is not None
        assert not info.arrived
        assert view.jpeg()[:2] == b"\xff\xd8"
        # The stream is a window around the star and its mark, not the whole sensor.
        assert camera.params is not None and camera.params.roi is not None
        assert camera.params.roi.width < WIDTH
    finally:
        await view.stop()
    assert view.info().state == "idle"


@pytest.mark.asyncio
async def test_follows_the_star_as_the_knobs_are_turned(tmp_path, monkeypatch) -> None:
    view, run, camera, moved, (exp_alt, exp_az) = _setup(tmp_path, monkeypatch, 5.0, 4.0, d_az=0.02, d_alt=-0.025)
    assert abs(exp_alt - 5.0) > 1.0 and abs(exp_az - 4.0) > 1.0  # the knob turn is a real change
    await view.start(run, StarViewRequest(exposure_s=0.2))
    try:
        await _wait_until(lambda: view.info().state == "tracking")
        await camera.glide(moved)
        await _wait_until(lambda: abs(view.info().alt_error_arcmin - exp_alt) < 0.8, timeout=5)
        info = view.info()
        assert info.alt_error_arcmin == pytest.approx(exp_alt, abs=0.8)
        assert info.az_error_arcmin == pytest.approx(exp_az, abs=0.8)
        assert run.live_offset is not None
        assert run.live_offset.alt_error_arcmin == pytest.approx(exp_alt, abs=0.8)
    finally:
        await view.stop()


@pytest.mark.asyncio
async def test_moving_the_star_onto_its_mark_removes_the_error(tmp_path, monkeypatch) -> None:
    view, run, camera, _moved, _expected = _setup(tmp_path, monkeypatch, 5.0, 4.0)
    await view.start(run, StarViewRequest(exposure_s=0.2))
    try:
        await _wait_until(lambda: view.info().state == "tracking")
        # Chase the mark: it moves a little as the error estimate settles.
        for _ in range(4):
            target = view.info().target
            assert target is not None
            await camera.glide(target, steps=8)
        await _wait_until(lambda: view.info().arrived, timeout=5)
        info = view.info()
        assert abs(info.alt_error_arcmin) < 0.6 and abs(info.az_error_arcmin) < 0.6
    finally:
        await view.stop()


@pytest.mark.asyncio
async def test_a_star_that_would_leave_the_frame_is_refused(tmp_path, monkeypatch) -> None:
    view, run, _camera, _moved, _expected = _setup(tmp_path, monkeypatch, 60.0, 50.0)
    await view.start(run, StarViewRequest(exposure_s=0.2))
    await _wait_until(lambda: view.info().state == "failed")
    assert "frame" in (view.info().error or "")


@pytest.mark.asyncio
async def test_losing_the_star_is_reported_and_recovered(tmp_path, monkeypatch) -> None:
    view, run, camera, _moved, _expected = _setup(tmp_path, monkeypatch, 5.0, 4.0)
    await view.start(run, StarViewRequest(exposure_s=0.2))
    try:
        await _wait_until(lambda: view.info().state == "tracking")
        camera.star = (-500.0, -500.0)  # clouds
        await _wait_until(lambda: view.info().state == "lost")
        camera.star = START
        await _wait_until(lambda: view.info().state == "tracking")
    finally:
        await view.stop()


def test_window_contains_star_and_target_and_stays_on_the_sensor() -> None:
    x0, y0, x1, y1 = _window_around((400.0, 300.0), (460.0, 250.0), WIDTH, HEIGHT)
    assert x0 <= 400 and 460 <= x1 and y0 <= 250 and 300 <= y1
    assert 0 <= x0 and x1 <= WIDTH and 0 <= y0 and y1 <= HEIGHT
    # Near a corner it is pushed back onto the sensor, keeping its size.
    x0, y0, x1, y1 = _window_around((5.0, 5.0), (20.0, 12.0), WIDTH, HEIGHT)
    assert (x0, y0) == (0, 0) and x1 - x0 >= 96 and y1 - y0 >= 96


@pytest.mark.asyncio
async def test_the_start_does_not_depend_on_where_the_exposure_put_the_star(tmp_path, monkeypatch) -> None:
    """The stream and the exposure the field was solved on may disagree by a pixel or two (8-bit
    streams, windows, centring conventions): the readings start from the stream's own position."""
    view, run, _camera, _moved, _expected = _setup(
        tmp_path, monkeypatch, 5.0, 4.0, exposure_star=(START[0] + 12.0, START[1] - 9.0)
    )
    await view.start(run, StarViewRequest(exposure_s=0.2))
    try:
        await _wait_until(lambda: view.info().state == "tracking")
        info = view.info()
        assert info.alt_error_arcmin == pytest.approx(5.0, abs=0.6)
        assert info.az_error_arcmin == pytest.approx(4.0, abs=0.6)
    finally:
        await view.stop()


@pytest.mark.asyncio
async def test_a_faint_star_is_flagged(tmp_path, monkeypatch) -> None:
    view, run, camera, _moved, _expected = _setup(tmp_path, monkeypatch, 5.0, 4.0)
    camera.amplitude, camera.noise = 5.0, 0.5  # a dim star in a quiet sky
    await view.start(run, StarViewRequest(exposure_s=0.2))
    try:
        await _wait_until(lambda: view.info().state == "tracking")
        assert view.info().weak
        camera.amplitude = 4000.0
        await _wait_until(lambda: not view.info().weak)
    finally:
        await view.stop()


@pytest.mark.asyncio
async def test_the_brightest_star_is_picked(tmp_path) -> None:
    pixels = _frame_pixels((200.0, 200.0))
    pixels += _frame_pixels((500.0, 400.0), amplitude=15000.0) - 200.0 - 0  # a brighter one, not clipped
    pixels = pixels.astype(np.float32)
    star = StarView._pick_star(StarView.__new__(StarView), pixels, 1.0, 1, (10.0, 10.0))
    assert (round(star.x), round(star.y)) == (500, 400)
