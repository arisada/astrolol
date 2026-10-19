"""Flats: the panel is closed and lit before the frames, and released afterwards."""

from __future__ import annotations

from pathlib import Path

from astrolol.core.sequencer import ExposureGroup, RunOutcome
from astrolol.plugins.sequencer.tests.fakes import Rig, make_task


def _flats(**kwargs: object):  # noqa: ANN202
    groups = [
        ExposureGroup(filter_name="L", duration=1, count=2, frame_type="flat", panel_brightness=80),
        ExposureGroup(filter_name="R", duration=1, count=1, frame_type="flat", panel_brightness=120),
    ]
    options: dict[str, object] = {
        "slew": False, "center": False, "start_guiding": False, "dither_every": None,
        "use_flat_panel": True,
    }
    options.update(kwargs)
    return make_task("Flats", groups, kind="current", ra=None, dec=None, **options)


async def _run(rig: Rig) -> RunOutcome | None:
    await rig.svc.start()
    return await rig.svc.wait_idle()


async def test_panel_is_closed_lit_per_group_and_released(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.svc.add(_flats())
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.panel.calls == [
        ("close", None),
        ("light", (True, 80)),
        ("light", (True, 120)),  # next group, other brightness; the cover is not touched again
        ("light", (False, None)),
        ("open", None),
    ]
    assert len(rig.imager.requests) == 3


async def test_without_the_option_the_panel_is_left_alone(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.svc.add(_flats(use_flat_panel=False))
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.panel.calls == []


async def test_unset_brightness_keeps_the_panel_level(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    task = make_task(
        "Flats", [ExposureGroup(duration=1, count=2, frame_type="flat")],
        kind="current", ra=None, dec=None, slew=False, center=False, start_guiding=False,
        dither_every=None, use_flat_panel=True,
    )
    await rig.svc.add(task)
    assert await _run(rig) == RunOutcome.COMPLETED
    assert rig.panel.calls[:2] == [("close", None), ("light", (True, None))]


async def test_panel_is_released_when_a_frame_fails(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.imager.fail_next = [RuntimeError("camera dropped")]
    await rig.svc.add(_flats(on_error="abort"))
    assert await _run(rig) != RunOutcome.COMPLETED
    # Whatever happened to the frames, the light is off and the cover open at the end.
    assert rig.panel.light_on is False
    assert rig.panel.cover == "open"


async def test_release_failure_is_reported_not_raised(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.panel.fail_on = "open"
    await rig.svc.add(_flats())
    assert await _run(rig) == RunOutcome.COMPLETED
    failed = rig.of("sequencer.step_failed")
    assert any(e.step == "flat_panel" and "open" in e.error for e in failed)


async def test_closing_failure_stops_the_task_before_any_frame(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.panel.fail_on = "close"
    await rig.svc.add(_flats(on_error="abort"))
    assert await _run(rig) != RunOutcome.COMPLETED
    assert rig.panel.light_on is False


async def test_preflight_requires_a_panel(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.dm.devices = [d for d in rig.dm.devices if d[1] != "flat_panel"]
    await rig.svc.add(_flats())
    report = await rig.svc.preflight()
    assert "no_flat_panel" in [i.code for i in report.issues]
    ok = Rig(tmp_path / "ok")
    await ok.svc.add(_flats())
    assert "no_flat_panel" not in [i.code for i in (await ok.svc.preflight()).issues]
