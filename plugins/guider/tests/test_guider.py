import asyncio
import math

import numpy as np
import pytest

from astrolol.core.events import EventBus
from astrolol.core.guiding import GuiderError, SettleFailed, SettleParams
from plugins.guider.calibration import Calibration, CalibrationFailed, calibrate
from plugins.guider.controller import AxisSettings
from plugins.guider.guider import BuiltinGuider
from plugins.guider.settings import GuiderSettings
from plugins.guider.tests.rig import Rig, RigDevices

FAST = dict(exposure=0.03, calibration_steps=5)
EASY_SETTLE = SettleParams(pixels=1.0, time=0, timeout=10)

ROTATED = np.array([[0.030 * math.cos(0.5), 0.030 * math.sin(0.5)],
                    [0.030 * math.sin(0.5), -0.030 * math.cos(0.5)]])  # rotated and mirrored


def make_guider(rig: Rig | None, **kw: object) -> BuiltinGuider:
    fine = AxisSettings(min_pulse_ms=2)  # the rig moves the star 0.03 px per ms: far finer than 20 ms
    return BuiltinGuider(EventBus(), GuiderSettings(**{**FAST, **kw}), RigDevices(rig), ra=fine, dec=fine)  # type: ignore[arg-type]


# --- calibration against a known matrix ---

async def _calibrate_rig(rig: Rig) -> Calibration:
    rig.drift_enabled = False
    pos = lambda: rig.star_positions()[0]  # noqa: E731

    async def measure():  # noqa: ANN202
        await asyncio.sleep(0)
        return pos()

    return await calibrate(measure, rig.pulse_guide, steps=5)


@pytest.mark.parametrize("matrix", [((0.03, 0), (0, 0.03)), ROTATED, ((0.008, 0), (0, 0.008))])
async def test_calibration_recovers_the_matrix(matrix) -> None:
    rig = Rig(matrix=matrix)
    cal = await _calibrate_rig(rig)
    assert np.allclose(cal.matrix, np.array(matrix), rtol=0.03, atol=1e-5)
    # and it inverts correctly
    west, north = cal.pulses_for(*(np.array(matrix) @ [100, 50]).tolist())
    assert (west, north) == pytest.approx((-100, -50), rel=0.03)


async def test_calibration_measures_dec_backlash() -> None:
    cal = await _calibrate_rig(Rig(dec_backlash_ms=150))
    assert np.allclose(cal.matrix, np.diag([0.03, 0.03]), rtol=0.03, atol=1e-5)
    assert 120 <= cal.dec_backlash_ms <= 180


async def test_calibration_fails_if_the_star_does_not_move() -> None:
    with pytest.raises(CalibrationFailed):
        await _calibrate_rig(Rig(matrix=np.zeros((2, 2))))


async def test_calibration_fails_if_axes_are_parallel() -> None:
    with pytest.raises(CalibrationFailed, match="same line"):
        await _calibrate_rig(Rig(matrix=((0.03, 0.03), (0.0, 0.0))))


# --- guiding ---

def rms_unguided(rig: Rig, seconds: float) -> float:
    return rig.drift[0] * seconds


@pytest.mark.parametrize("matrix", [((0.03, 0), (0, 0.03)), ROTATED])
async def test_guiding_holds_the_star_against_drift(matrix) -> None:
    rig = Rig(matrix=matrix, drift=(4.0, 1.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    assert g.status().guiding and g.status().state == "Guiding"
    start = g.mark()
    await asyncio.sleep(1.5)
    stats = g.stats(start)
    await g.stop()
    assert stats.steps > 10
    assert stats.rms_total is not None and stats.rms_total < 0.6, stats  # drift alone: 6 px in 1.5 s
    assert g.status().state == "Stopped" and not g.status().active


async def test_calibration_is_reused_between_runs() -> None:
    rig = Rig()
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    await g.stop()
    cal, pulses_before = g.calibration, len(rig.pulses)
    await g.guide(EASY_SETTLE)
    await g.stop()
    assert g.calibration is cal
    assert all(ms < 90 for _, ms in rig.pulses[pulses_before:])  # corrections only, no sweep
    await g.guide(EASY_SETTLE, recalibrate=True)
    await g.stop()
    assert g.calibration is not cal


async def test_stream_window_follows_the_stars() -> None:
    rig = Rig(stars=((100.0, 80.0, 700.0),))
    g = make_guider(rig, star_count=1)
    await g.guide(EASY_SETTLE)
    roi_used = rig._task is not None  # streaming
    await g.stop()
    assert roi_used


async def test_dither_moves_the_star_and_settles() -> None:
    rig = Rig(drift=(0.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    before = np.array(rig.star_positions()[0])
    await g.dither(4.0, False, EASY_SETTLE)
    after = np.array(rig.star_positions()[0])
    await g.stop()
    assert 2.0 < np.linalg.norm(after - before) < 6.0  # settled to within 1 px at both ends


async def test_dither_requires_guiding() -> None:
    with pytest.raises(GuiderError):
        await make_guider(Rig()).dither(3, False, EASY_SETTLE)


async def test_losing_the_star_reports_and_recovers() -> None:
    rig = Rig(drift=(1.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    rig.hidden = True
    await asyncio.sleep(0.5)
    assert not g.health().guiding and g.health().reason == "star_lost"
    rig.hidden = False
    await asyncio.sleep(0.7)
    assert g.health().guiding
    await g.stop()


async def test_guiding_gives_up_when_the_star_stays_lost() -> None:
    rig = Rig(drift=(1.0, 0.0))
    g = make_guider(rig, lost_timeout_s=0.4)
    await g.guide(EASY_SETTLE)
    rig.hidden = True
    await asyncio.sleep(1.2)
    assert not g.status().active


async def test_settle_times_out_when_the_error_never_gets_small() -> None:
    g = make_guider(Rig(drift=(1.0, 0.0)))
    with pytest.raises(SettleFailed, match="timed-out"):
        await g.guide(SettleParams(pixels=0.001, time=5, timeout=1))  # tighter than the noise
    await g.stop()


async def test_no_star_is_a_clear_error() -> None:
    rig = Rig(stars=())
    with pytest.raises(GuiderError, match="No suitable guide star"):
        await make_guider(rig).guide(EASY_SETTLE)


async def test_missing_camera_is_a_clear_error() -> None:
    with pytest.raises(GuiderError, match="no guide camera"):
        await make_guider(None).guide(EASY_SETTLE)


async def test_pause_stops_the_corrections() -> None:
    rig = Rig()
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    await g.pause()
    await asyncio.sleep(0.15)  # a pulse already under way may still land
    n = len(rig.pulses)
    await asyncio.sleep(0.4)
    assert len(rig.pulses) == n and g.status().state == "Paused"
    await g.resume()
    await asyncio.sleep(0.4)
    assert len(rig.pulses) > n
    await g.stop()


# --- what the UI shows ---

async def test_preview_shows_the_stars_it_would_pick() -> None:
    g = make_guider(Rig())
    await g.start_preview()
    await asyncio.sleep(0.5)
    info = g.view.info()
    assert g.status().state == "Previewing" and not g.status().active
    assert info.mode == "preview" and (info.width, info.height) == (200, 160)
    kinds = sorted(s.kind for s in info.stars)
    assert kinds == ["companion", "companion", "primary"]
    primary = next(s for s in info.stars if s.kind == "primary")
    assert (round(primary.x), round(primary.y)) == (100, 80)
    assert g.view.jpeg()[:2] == b"\xff\xd8"  # a JPEG
    await g.stop_preview()
    assert g.view.info().mode == "idle" and g.view.info().stars == []


async def test_preview_marks_candidates_that_were_not_picked() -> None:
    rig = Rig(stars=((100.0, 80.0, 700.0), (60.0, 50.0, 500.0), (150.0, 110.0, 450.0), (40.0, 120.0, 400.0)))
    g = make_guider(rig, star_count=2)
    await g.start_preview()
    await asyncio.sleep(0.5)
    kinds = sorted(s.kind for s in g.view.info().stars)
    assert kinds == ["candidate", "candidate", "companion", "primary"]
    await g.stop_preview()


async def test_guiding_takes_over_from_the_preview() -> None:
    g = make_guider(Rig())
    await g.start_preview()
    await asyncio.sleep(0.2)
    await g.guide(EASY_SETTLE)
    assert g.status().state == "Guiding" and g.view.info().mode == "guiding"
    await g.stop()


async def test_preview_refused_while_guiding() -> None:
    g = make_guider(Rig())
    await g.guide(EASY_SETTLE)
    with pytest.raises(GuiderError, match="Already guiding"):
        await g.start_preview()
    await g.stop()


async def test_view_follows_the_stars_while_guiding() -> None:
    rig = Rig(drift=(1.0, 0.0))
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    info = g.view.info()
    assert info.mode == "guiding" and len(info.locks) == 3
    assert {s.kind for s in info.stars} <= {"primary", "companion"}
    truth = rig.star_positions()
    primary = next(s for s in info.stars if s.kind == "primary")
    assert abs(primary.x - truth[0][0]) < 3 and abs(primary.y - truth[0][1]) < 3
    await g.stop()
    assert g.view.info().mode == "idle"


async def test_guide_steps_are_published() -> None:
    rig = Rig(drift=(4.0, 1.0))
    g = make_guider(rig)
    queue = g._bus.subscribe()
    await g.guide(EASY_SETTLE)
    await asyncio.sleep(0.6)
    await g.stop()
    steps = []
    while not queue.empty():
        e = queue.get_nowait()
        if getattr(e, "type", "") == "guider.step":
            steps.append(e)
    assert len(steps) > 5
    assert any(s.ra_corr != 0 for s in steps)           # it corrected the drift
    assert all(s.stars_found >= 1 for s in steps)
    assert all(abs(s.ra_dist) < 5 and abs(s.dec_dist) < 5 for s in steps)


# --- calibration under trouble, and what it records ---

async def test_calibration_waits_out_smeared_frames() -> None:
    rig = Rig(drift=(1.0, 0.5), smear_frames_after_pulse=2)
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    cal = g.calibration
    await g.stop()
    assert cal is not None and np.allclose(cal.matrix, np.diag([0.03, 0.03]), rtol=0.05, atol=1e-4)


async def test_calibration_waits_out_missing_frames() -> None:
    rig = Rig(drift=(1.0, 0.5), lose_frames_after_pulse=2)
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    cal = g.calibration
    await g.stop()
    assert cal is not None and np.allclose(cal.matrix, np.diag([0.03, 0.03]), rtol=0.05, atol=1e-4)


async def test_calibration_gives_up_clearly_when_the_star_never_comes_back() -> None:
    rig = Rig(lose_frames_after_pulse=10_000)
    g = make_guider(rig)
    with pytest.raises(GuiderError, match="Lost the guide star during calibration"):
        await g.guide(EASY_SETTLE)


async def test_calibration_keeps_every_measurement() -> None:
    rig = Rig(drift=(2.0, -1.0), dec_backlash_ms=150)
    g = make_guider(rig)
    await g.guide(EASY_SETTLE)
    cal = g.calibration
    await g.stop()
    phases = [p.phase for p in cal.trace]
    for phase in ("drift", "probe", "west", "east", "north", "south"):
        assert phase in phases
    ts = [p.t for p in cal.trace]
    assert ts == sorted(ts)
    assert (cal.drift_x, cal.drift_y) == pytest.approx((2.0, -1.0), abs=0.6)
    # The slack at the start of the way back is left out of the fit, and marked as such.
    south = [p for p in cal.trace if p.phase == "south"]
    assert any(not p.used for p in south) and sum(p.used for p in south) >= 4
    assert not any(p.used for p in cal.trace if p.phase in ("drift", "probe"))
    assert 120 <= cal.dec_backlash_ms <= 180


async def test_the_way_back_is_a_second_reading_of_the_speed() -> None:
    cal = await _calibrate_rig(Rig(matrix=((0.03, 0), (0, 0.03))))
    assert cal.ra_rate == pytest.approx(0.03, rel=0.03)
    assert [p.phase for p in cal.trace].count("east") == 6  # the way back: 5 pulses and the start


# --- Dec backlash compensation ---



async def _guided_dec_rms(compensate: bool) -> float:
    # The star swings in Dec by +-2.5 px every 1.2 s, so corrections keep reversing; each reversal
    # costs 150 ms of pulse (4.5 px) in the gears.
    rig = Rig(drift=(0.0, 0.0), dec_backlash_ms=150, dec_wobble=(0.0, 1.2), seed=3)
    g = make_guider(rig, dec_backlash_compensation=compensate)
    await g.guide(EASY_SETTLE)
    rig.dec_wobble = (2.5, 1.2)
    await asyncio.sleep(0.3)
    start = g.mark()
    await asyncio.sleep(3.0)
    rms = g.stats(start).rms_dec
    await g.stop()
    return rms


async def test_backlash_compensation_improves_dec_guiding() -> None:
    plain = await _guided_dec_rms(False)
    compensated = await _guided_dec_rms(True)
    assert compensated < plain * 0.85, (plain, compensated)
