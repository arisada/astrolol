"""The guider through what a night throws at it: glitches, refused pulses, a failing camera,
clouds, a bumped mount, slews, meridian flips and other declinations."""
import asyncio
import contextlib
import math

import numpy as np
import pytest

from astrolol.core.events import EventBus
from astrolol.core.guiding import GuiderError, SettleParams
from astrolol.plugins.guider import guider as guider_module
from astrolol.plugins.guider.calibration import Calibration
from astrolol.plugins.guider.controller import AxisSettings
from astrolol.plugins.guider.guider import BuiltinGuider
from astrolol.plugins.guider.settings import GuiderSettings
from astrolol.plugins.guider.tests.rig import Rig, RigDevices

EASY_SETTLE = SettleParams(pixels=1.0, time=0, timeout=10)


def make_guider(rig: Rig | None, *, calibration_file=None, **kw: object) -> BuiltinGuider:  # noqa: ANN001
    fine = AxisSettings(min_pulse_ms=2)
    settings = GuiderSettings(**{"exposure": 0.03, "calibration_steps": 5, **kw})
    return BuiltinGuider(EventBus(), settings, RigDevices(rig), ra=fine, dec=fine, calibration_file=calibration_file)  # type: ignore[arg-type]


def star_error(rig: Rig, g: BuiltinGuider) -> float:
    """Distance of the primary from its lock, as the rig knows it."""
    x, y = rig.star_positions()[0]
    lx, ly = g.view.info().locks[0]
    return math.hypot(x - lx, y - ly)


async def test_pausing_is_not_reported_as_guiding() -> None:
    g = make_guider(Rig())
    await g.guide(EASY_SETTLE)
    await g.pause()
    await asyncio.sleep(0.4)
    assert not g.health().guiding and g.health().reason == "paused"
    start = g.mark()
    await asyncio.sleep(0.3)
    assert g.stats(start).steps == 0  # a paused stretch is not counted as guided
    await g.resume()
    await asyncio.sleep(0.3)
    assert g.health().guiding
    await g.stop()


async def test_a_one_frame_jump_is_not_corrected() -> None:
    rig = Rig(drift=(0.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    await asyncio.sleep(0.5)  # the jump check learns the noise
    n = len(rig.pulses)
    rig.flash = (1, 15.0, 0.0)  # a satellite, a cosmic ray: one frame far off
    await asyncio.sleep(0.4)
    big = [ms for _, ms in rig.pulses[n:] if ms > 100]
    assert big == []  # 15 px would be a 500 ms pulse
    await g.stop()


async def test_a_real_move_is_followed_after_a_few_frames() -> None:
    rig = Rig(drift=(0.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    await asyncio.sleep(0.5)
    rig.offset += (6.0, 0.0)  # a gust that moved the mount and left it there
    await asyncio.sleep(1.5)
    assert star_error(rig, g) < 1.0  # walked back to the lock
    await g.stop()


async def test_refused_pulses_do_not_end_guiding() -> None:
    rig = Rig(drift=(3.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    rig.fail_pulses = 6
    await asyncio.sleep(0.6)
    assert g.status().active
    await asyncio.sleep(0.8)
    assert g.health().guiding and star_error(rig, g) < 1.0
    await g.stop()


async def test_refused_pulses_are_reported_as_not_guiding() -> None:
    rig = Rig(drift=(3.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    rig.fail_pulses = 10_000
    await asyncio.sleep(0.8)
    assert g.status().active and not g.health().guiding and g.health().reason == "pulse_failed"
    rig.fail_pulses = 0
    await asyncio.sleep(0.8)
    assert g.health().guiding
    await g.stop()


async def test_a_camera_that_fails_is_restarted() -> None:
    rig = Rig(drift=(1.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    rig.end_stream(RuntimeError("USB reset"))
    await asyncio.sleep(1.5)
    assert g.status().active and g.health().guiding
    assert star_error(rig, g) < 1.0
    await g.stop()


async def test_a_camera_that_stalls_is_restarted(monkeypatch) -> None:  # noqa: ANN001
    rig = Rig(drift=(1.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    monkeypatch.setattr(BuiltinGuider, "_frame_wait", property(lambda self: 0.05))
    rig.stalled = True
    await asyncio.sleep(0.2)
    rig.stalled = False
    original = g._next_frame

    async def short_timeout(sub, newer_than, *, timeout=None):  # noqa: ANN001, ANN202
        return await original(sub, newer_than, timeout=timeout if timeout is not None else 0.5)

    monkeypatch.setattr(g, "_next_frame", short_timeout)
    await asyncio.sleep(2.0)
    assert g.status().active and g.health().guiding
    await g.stop()


async def test_a_camera_that_keeps_failing_ends_the_run_with_the_reason(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(guider_module, "STREAM_RETRIES", 1)
    rig = Rig()
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)

    async def broken(params) -> None:  # noqa: ANN001
        raise RuntimeError("camera gone")

    rig.start_stream = broken  # type: ignore[method-assign]
    rig.end_stream(RuntimeError("camera gone"))
    for _ in range(40):
        await asyncio.sleep(0.1)
        if not g.status().active:
            break
    assert not g.status().active
    assert g.last_error and "stopped sending frames" in g.last_error


async def test_the_star_is_found_again_after_clouds_and_a_bump(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(guider_module, "FULL_SEARCH_AFTER_S", 0.3)
    monkeypatch.setattr(guider_module, "FULL_SEARCH_EVERY_S", 0.1)
    rig = Rig(drift=(0.0, 0.0), shape=(240, 320),
              stars=((150.0, 110.0, 700.0), (110.0, 80.0, 500.0), (200.0, 140.0, 450.0)))
    g = make_guider(rig, lost_timeout_s=0)
    await g.guide(EASY_SETTLE)
    assert g._roi is not None  # tracking a window
    rig.hidden = True
    rig.offset += (70.0, -45.0)  # bumped while the clouds passed: far outside the window
    await asyncio.sleep(0.8)
    assert g.status().active and not g.health().guiding
    rig.hidden = False
    for _ in range(40):
        await asyncio.sleep(0.1)
        if g.health().guiding:
            break
    assert g.health().guiding
    await asyncio.sleep(2.5)
    assert star_error(rig, g) < 1.5  # and walked back to where it was locked
    await g.stop()


async def test_guiding_stops_when_the_mount_slews() -> None:
    rig = Rig()
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    rig.slewing = True
    for _ in range(40):
        await asyncio.sleep(0.1)
        if not g.status().active:
            break
    assert not g.status().active
    assert g.health().reason == "mount_moved" and "slewed" in (g.last_error or "")


async def test_guiding_does_not_start_while_the_mount_slews() -> None:
    rig = Rig()
    rig.slewing = True
    with pytest.raises(GuiderError, match="slewing"):
        await make_guider(rig).guide(EASY_SETTLE)


async def test_two_starts_at_once_make_one_run() -> None:
    g = make_guider(Rig())
    outcomes = await asyncio.gather(
        g.guide(EASY_SETTLE, wait_settle=False), g.guide(EASY_SETTLE, wait_settle=False), return_exceptions=True
    )
    assert all(o is None or isinstance(o, GuiderError) for o in outcomes)  # the second is busy, at worst
    task = g._task
    await asyncio.sleep(0.2)
    assert g._task is task
    await g.stop()


# --- pointing: declination and meridian flips ---

async def _hold(rig: Rig, g: BuiltinGuider, seconds: float = 1.5) -> float:
    await g.guide(EASY_SETTLE)
    await asyncio.sleep(0.3)
    start = g.mark()
    await asyncio.sleep(seconds)
    stats = g.stats(start)
    await g.stop()
    return stats.rms_total or 0.0


async def test_a_calibration_follows_the_declination() -> None:
    rig = Rig(dec=0.0, pier_side="West", drift=(2.0, 0.5))
    g = make_guider(rig)
    await _hold(rig, g, 0.5)
    made = g.calibration
    assert made.dec == 0.0 and made.pier_side == "West"
    rig.dec = 60.0
    rig.matrix[:, 0] *= 0.5  # the sky turns half as fast under the pulses at dec 60
    await g.guide(EASY_SETTLE)
    assert g.calibration is made  # not calibrated again
    assert g.active_calibration.ra_rate == pytest.approx(made.ra_rate / 2, rel=0.02)
    await g.stop()


@pytest.mark.parametrize("sky_dec", [False, True])
async def test_guiding_after_a_meridian_flip(sky_dec) -> None:
    rig = Rig(dec=20.0, pier_side="East", sky_dec_pulses=sky_dec, drift=(2.0, 1.0))
    g = make_guider(rig, guide_output="mount" if sky_dec else "camera")  # auto guesses right
    await _hold(rig, g, 0.5)
    rig.flip()
    rms = await _hold(rig, g)
    assert rms < 0.6
    assert g.health().reason != "axis_reversed"


async def test_a_wrong_flip_guess_is_caught_and_remembered() -> None:
    rig = Rig(dec=20.0, pier_side="East", sky_dec_pulses=True, drift=(0.0, 3.0))
    g = make_guider(rig, flip_dec_after_meridian_flip="no")  # wrong for this mount
    await _hold(rig, g, 0.5)
    rig.flip()
    await g.guide(EASY_SETTLE)
    for _ in range(40):
        await asyncio.sleep(0.1)
        if g.calibration.flip_dec is not None:
            break
    assert g.calibration.flip_dec is True  # learned: North follows the sky on this mount
    await asyncio.sleep(1.0)
    assert g.status().active and star_error(rig, g) < 1.0
    await g.stop()


async def test_guiding_that_keeps_diverging_stops() -> None:
    rig = Rig(drift=(0.0, 0.0))
    g = make_guider(rig)
    # A calibration whose both axes are wrong in a way reversing them does not fix: rotated by
    # 90 degrees, so every correction goes sideways.
    g.calibration = Calibration(ra_x=0.0, ra_y=0.03, dec_x=-0.03, dec_y=0.0)
    await g.guide(SettleParams(pixels=1.0, time=0, timeout=10), wait_settle=False)
    rig.offset += (5.0, 3.0)
    for _ in range(80):
        await asyncio.sleep(0.1)
        if not g.status().active:
            break
    assert not g.status().active or star_error(rig, g) < 1.0
    await g.stop()


# --- the calibration is kept ---

async def test_the_calibration_survives_a_restart(tmp_path) -> None:  # noqa: ANN001
    file = tmp_path / "calibration.json"
    g = make_guider(Rig(), calibration_file=file, camera_id="cam1")
    await g.guide(EASY_SETTLE)
    await g.stop()
    again = make_guider(Rig(), calibration_file=file, camera_id="cam1")
    assert again.calibration is not None
    assert again.calibration.matrix.tolist() == g.calibration.matrix.tolist()
    assert again.calibration.camera_id == "cam1"


async def test_another_camera_means_another_calibration(tmp_path) -> None:  # noqa: ANN001
    file = tmp_path / "calibration.json"
    g = make_guider(Rig(), calibration_file=file, camera_id="cam1")
    await g.guide(EASY_SETTLE)
    await g.stop()
    await g.update_settings(g.settings.model_copy(update={"camera_id": "cam2"}))
    assert g.calibration is None and not file.exists()


async def test_a_failed_calibration_is_kept_for_the_page() -> None:
    rig = Rig(matrix=((0.03, 0.0), (0.0, 0.0)))  # Dec does not move
    g = make_guider(rig)
    with pytest.raises(GuiderError):
        await g.guide(EASY_SETTLE)
    attempt = g.calibration_attempt
    assert attempt is not None and not attempt.running and "N pulses" in (attempt.error or "")
    assert any(p.phase == "west" for p in attempt.trace)
    assert g.last_error and "N pulses" in g.last_error


# --- real-world stars and sky ---

async def test_guiding_under_seeing_and_periodic_error_beats_no_guiding() -> None:
    # 0.4 px of seeing per frame and a 6 px periodic error over 3 s.
    rig = Rig(seeing_px=0.4, pe=(6.0, 3.0), drift=(0.5, 0.2), seed=4)
    g = make_guider(rig, star_count=3)
    rms = await _hold(rig, g, 3.0)
    unguided = 6.0 / math.sqrt(2)
    assert rms < unguided / 3, rms


async def test_guiding_on_elongated_stars() -> None:
    rig = Rig(star_sigma=(4.0, 1.8), drift=(2.0, 0.5))  # comatic stars at the edge of an OAG
    g = make_guider(rig)
    rms = await _hold(rig, g, 1.0)
    assert rms < 0.6
    assert g.health().reason == "stopped"


async def test_a_saturated_star_is_not_the_guide_star() -> None:
    rig = Rig(stars=((100.0, 80.0, 30000.0), (60.0, 50.0, 500.0), (150.0, 110.0, 450.0)), max_adu=4095)
    g = make_guider(rig, star_count=1)
    await g.start_preview()
    await asyncio.sleep(0.5)
    primary = next(s for s in g.view.info().stars if s.kind == "primary")
    await g.stop_preview()
    assert (round(primary.x), round(primary.y)) != (100, 80)


async def test_the_star_the_user_picked_is_guided_on() -> None:
    rig = Rig()
    g = make_guider(rig)
    await g.start_preview()
    await asyncio.sleep(0.5)
    assert g.select_star(151 + rig.drift[0] * 0.5, 109) is not None  # the third star, not the brightest
    await g.stop_preview()
    await g.guide(EASY_SETTLE)
    primary = next(s for s in g.view.info().stars if s.kind == "primary")
    truth = rig.star_positions()[2]
    assert (primary.x, primary.y) == pytest.approx(truth, abs=2)
    await g.stop()
    assert g.preferred_star is None  # one run only


def test_rig_flip_matrix() -> None:
    rig = Rig(sky_dec_pulses=True, pier_side="East")
    before = rig.matrix.copy()
    rig.flip()
    assert np.allclose(rig.matrix, -before) and rig.pier_side == "West"


async def test_the_corrections_follow_the_settings() -> None:
    rig = Rig(drift=(3.0, 0.0))
    g = BuiltinGuider(EventBus(), GuiderSettings(
        exposure=0.03, calibration_steps=5, ra_aggressiveness=0.4, dec_aggressiveness=0.3,
        min_move_px=0.05, max_pulse_ms=300, min_pulse_ms=2, dec_mode="north", pixel_scale=1.0,
    ), RigDevices(rig))
    await g.guide(EASY_SETTLE)
    c = g._controller
    assert (c.ra.aggressiveness, c.dec.aggressiveness, c.dec_mode) == (0.4, 0.3, "north")
    assert c.ra.min_move_px == 0.05 and c.ra.max_pulse_ms == 300 and c.dec.resist_switch
    n = len(rig.pulses)
    await asyncio.sleep(0.5)
    assert not any(d == "S" for d, _ in rig.pulses[n:])  # North only
    await g.stop()


@pytest.mark.parametrize("predict", [False, True])
async def test_a_steady_drift_is_held_on_the_lock(predict) -> None:
    # Slow frames and a steady drift: proportional corrections alone trail it.
    rig = Rig(drift=(3.0, 0.0))
    g = make_guider(rig, exposure=0.15, predict_drift=predict)
    queue = g._bus.subscribe()
    await g.guide(EASY_SETTLE)
    await asyncio.sleep(4.0)
    ras = []
    while not queue.empty():
        e = queue.get_nowait()
        if getattr(e, "type", "") == "guider.step":
            ras.append(e.ra_dist)
    await g.stop()
    late = ras[len(ras) // 2:]
    mean = abs(sum(late) / len(late))
    if predict:
        assert mean < 0.2, mean
    else:
        assert mean > 0.3, mean  # the lag prediction removes


@pytest.mark.slow
async def test_a_night_of_incidents(monkeypatch) -> None:  # noqa: ANN001
    """Seeing, periodic error, drift and backlash, with clouds, glitches, refused pulses, camera
    failures, bumps and dithers every few seconds: guiding must survive and keep the star."""
    import random

    monkeypatch.setattr(guider_module, "FULL_SEARCH_AFTER_S", 1.0)
    monkeypatch.setattr(guider_module, "FULL_SEARCH_EVERY_S", 0.3)
    rnd = random.Random(7)
    rig = Rig(seeing_px=0.3, pe=(4.0, 6.0), drift=(1.5, 0.5), dec_backlash_ms=80, seed=7, shape=(240, 320),
              stars=((150.0, 110.0, 800.0), (110.0, 80.0, 500.0), (200.0, 150.0, 450.0)))
    g = make_guider(rig, exposure=0.05)
    queue = g._bus.subscribe()
    await g.guide(SettleParams(pixels=1.5, time=0, timeout=20))
    for _ in range(60):
        await asyncio.sleep(1.0)
        assert g.status().active, g.last_error
        r = rnd.random()
        if r < 0.05:
            rig.hidden = True
            await asyncio.sleep(rnd.uniform(0.5, 3))
            rig.hidden = False
        elif r < 0.10:
            rig.flash = (1, rnd.uniform(-20, 20), rnd.uniform(-20, 20))
        elif r < 0.14:
            rig.fail_pulses = rnd.randint(1, 8)
        elif r < 0.17:
            rig.end_stream(RuntimeError("usb"))
        elif r < 0.20:
            rig.offset += (rnd.uniform(-8, 8), rnd.uniform(-8, 8))
        elif r < 0.27 and g.health().guiding:
            with contextlib.suppress(GuiderError):
                await g.dither(rnd.uniform(1, 5), False, SettleParams(pixels=1.5, time=0, timeout=15))
    await asyncio.sleep(2.0)
    assert g.health().guiding
    errors = []
    while not queue.empty():
        e = queue.get_nowait()
        if getattr(e, "type", "") == "guider.step":
            errors.append(math.hypot(e.ra_dist, e.dec_dist))
    await g.stop()
    errors.sort()
    assert errors[len(errors) // 2] < 1.0  # median, dithers included


async def test_the_periodic_error_is_learnt_while_guiding() -> None:
    # A fast 'worm' (2.5 s) so that a few periods pass in a test; slow frames so that
    # corrections made afterwards trail it.
    rig = Rig(drift=(0.0, 0.0), seeing_px=0.1, seed=2)
    g = make_guider(rig, exposure=0.08)
    await g.guide(EASY_SETTLE)
    rig.pe = (5.0, 2.5)  # a real worm turns in minutes: calibration sees only part of a period
    for _ in range(80):
        await asyncio.sleep(0.25)
        p = g.prediction()
        if p and p.pe_period_s:
            break
    p = g.prediction()
    await g.stop()
    assert p is not None and p.pe_period_s == pytest.approx(2.5, rel=0.1), p
    assert p.pe_amplitude == pytest.approx(10.0, rel=0.35)  # peak to peak


async def test_binning_reaches_the_camera_scale_and_calibration() -> None:
    async def optics(camera_id: str | None) -> float | None:
        return 1.5

    rig = Rig()
    seen: list[int] = []
    start = rig.start_stream

    async def spy(params):  # noqa: ANN001, ANN202
        seen.append(params.binning)
        await start(params)

    rig.start_stream = spy  # type: ignore[method-assign]
    fine = AxisSettings(min_pulse_ms=2)
    g = BuiltinGuider(EventBus(), GuiderSettings(exposure=0.03, calibration_steps=5, binning=2), RigDevices(rig),
                      ra=fine, dec=fine, scale_resolver=optics)
    await g.guide(EASY_SETTLE)
    assert set(seen) == {2} and g.status().pixel_scale == 3.0 and g.calibration.binning == 2
    with pytest.raises(GuiderError, match="binning"):
        await g.update_settings(g.settings.model_copy(update={"binning": 1}))
    await g.stop()
    await g.update_settings(g.settings.model_copy(update={"binning": 1}))
    assert g.calibration is None  # made binned 2x2: pulses move the star half as many pixels now


async def test_stopping_during_calibration_leaves_no_attempt_behind() -> None:
    g = make_guider(Rig(), exposure=0.1)
    await g.guide(EASY_SETTLE, wait_settle=False)
    for _ in range(50):
        await asyncio.sleep(0.05)
        if g.calibration_attempt and g.calibration_attempt.trace:
            break
    assert g.calibration_attempt is not None and g.calibration_attempt.running
    await g.stop()
    assert g.calibration_attempt is None and g.calibration is None


async def test_a_camera_that_ignores_windows_is_asked_only_once() -> None:
    # Stars in the far corner, so a window taken from the sensor's corner misses them.
    rig = Rig(shape=(240, 320), drift=(0.0, 0.0), stars=((260.0, 185.0, 700.0), (235.0, 170.0, 500.0), (250.0, 160.0, 450.0)))
    starts: list[object] = []
    start = rig.start_stream

    async def wrong_windows(params):  # noqa: ANN001, ANN202
        starts.append(params.roi)
        roi = params.roi
        # A driver that sends a window of the size asked for, but from the sensor's corner.
        await start(params.model_copy(update={"roi": roi and roi.model_copy(update={"x": 0, "y": 0})}))

    rig.start_stream = wrong_windows  # type: ignore[method-assign]
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    await asyncio.sleep(0.5)
    assert g.health().guiding
    await g.stop()
    assert sum(r is not None for r in starts) == 1
    assert len(starts) <= 4  # first frame, the window, back to full frames (and no more)
