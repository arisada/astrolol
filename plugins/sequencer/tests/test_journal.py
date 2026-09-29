"""Session journal: writing, summaries, exports, routes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.sequencer import ExposureGroup, RunOutcome
from plugins.sequencer.api import router
from plugins.sequencer.journal import (
    JournalWriter,
    default_journal_dir,
    find_session,
    frames_csv,
    read_records,
    session_files,
    summarize,
    summary_markdown,
)
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.tests.fakes import Rig, make_task, wait_until


@pytest.fixture
async def journaled(tmp_path: Path):  # type: ignore[no-untyped-def]
    rig = Rig(tmp_path, SequencerSettings(guide_healthy_after_s=0))
    journal_dir = tmp_path / "journal"
    writer = JournalWriter(
        rig.bus,
        lambda: journal_dir,
        lambda: {
            "settings": {},
            "equipment": [],
            "tasks": [e.model_dump(mode="json") for e in rig.svc.entries],
        },
    )
    await writer.start()
    rig.journal = writer  # type: ignore[attr-defined]
    rig.journal_dir = journal_dir  # type: ignore[attr-defined]
    yield rig
    await writer.stop()


def _finished(rig: Rig) -> bool:
    files = session_files(rig.journal_dir)  # type: ignore[attr-defined]
    records = read_records(files[0]) if files else []
    return bool(records) and records[-1]["type"] == "sequencer.session_finished"


async def _run(rig: Rig) -> RunOutcome | None:
    await rig.svc.start()
    outcome = await rig.svc.wait_idle()
    await wait_until(lambda: _finished(rig))
    return outcome


async def test_a_run_writes_one_journal_file(journaled: Rig) -> None:
    rig = journaled
    await rig.svc.add(
        make_task(
            "M 42",
            groups=[
                ExposureGroup(filter_name="R", duration=60, count=2),
                ExposureGroup(filter_name="G", duration=30, count=1),
            ],
        )
    )
    assert await _run(rig) == RunOutcome.COMPLETED
    files = session_files(rig.journal_dir)  # type: ignore[attr-defined]
    assert len(files) == 1
    records = read_records(files[0])
    types = [r["type"] for r in records]
    assert types[0] == "sequencer.session_started"
    assert types[1] == "journal.context"
    assert types[-1] == "sequencer.session_finished"
    assert types.count("sequencer.frame_saved") == 3
    assert "journal.activity" in types
    assert "sequencer.status" not in types and "sequencer.queue_changed" not in types
    frame = next(r for r in records if r["type"] == "sequencer.frame_saved")
    assert frame["object_name"] == "M 42" and frame["hour_angle"] is not None


async def test_summary(journaled: Rig) -> None:
    rig = journaled
    rig.guider.unguided_s = 5.0
    await rig.svc.add(
        make_task(
            "M 42",
            groups=[
                ExposureGroup(filter_name="R", duration=60, count=2),
                ExposureGroup(filter_name="G", duration=30, count=1),
            ],
        )
    )
    await _run(rig)
    path = session_files(rig.journal_dir)[0]  # type: ignore[attr-defined]
    s = summarize(path, read_records(path))
    assert s.outcome == "completed"
    assert s.frames_saved == 3 and s.integration_s == 150
    assert [(r.object_name, r.filter_name, r.frames, r.seconds) for r in s.integration] == [
        ("M 42", "G", 1, 30),
        ("M 42", "R", 2, 120),
    ]
    assert s.tasks == ["M 42"]
    labels = {t.activity for t in s.time}
    assert "exposing" in labels
    assert abs(sum(t.seconds for t in s.time) - s.duration_s) < 0.5
    assert find_session(rig.journal_dir, s.session_id) == path  # type: ignore[attr-defined]


async def test_interruptions_and_stalls_are_reported(journaled: Rig, tmp_path: Path) -> None:
    rig = journaled
    rig.imager.gate = asyncio.Event()
    await rig.svc.add(make_task("A", groups=[ExposureGroup(duration=1, count=3)]))
    await rig.svc.start()
    await wait_until(lambda: rig.imager.exposing)
    await rig.svc.stop("now", actor="user", reason="clouds")
    await rig.svc.wait_idle()
    await wait_until(lambda: _finished(rig))
    path = session_files(rig.journal_dir)[0]  # type: ignore[attr-defined]
    records = read_records(path)
    s = summarize(path, records)
    assert s.outcome == "stopped" and s.interruptions == 1 and s.frames_discarded == 1
    md = summary_markdown(s, records)
    assert "stop by user: clouds" in md and "## Where the time went" in md


async def test_exports(journaled: Rig) -> None:
    rig = journaled
    await rig.svc.add(make_task(groups=[ExposureGroup(filter_name="L", duration=10, count=2)]))
    await _run(rig)
    records = read_records(session_files(rig.journal_dir)[0])  # type: ignore[attr-defined]
    csv_text = frames_csv(records)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("timestamp,object_name,camera_id,filter_name,duration")
    assert len(lines) == 3 and ",cam1,L,10.0," in lines[1]


def test_a_crash_leaves_a_readable_file(tmp_path: Path) -> None:
    path = tmp_path / "2026-09-29_2100_abcdef123456.jsonl"
    started = {
        "type": "sequencer.session_started",
        "timestamp": "2026-09-29T21:00:00+00:00",
        "session_id": "abcdef123456",
        "actor": "user",
    }
    frame = {
        "type": "sequencer.frame_saved",
        "timestamp": "2026-09-29T21:05:00+00:00",
        "task_id": "t1",
        "lane_id": "l1",
        "group_idx": 0,
        "frame_idx": 0,
        "frames_total": 5,
        "filter_name": None,
        "duration": 300.0,
        "fits_path": "/x.fits",
        "object_name": "M 31",
    }
    path.write_text(
        json.dumps(started) + "\n" + json.dumps(frame) + "\n" + '{"type": "sequencer.fra'
    )
    records = read_records(path)
    s = summarize(path, records)
    assert len(records) == 2
    assert s.outcome is None and s.finished_at is None
    assert s.frames_saved == 1 and s.duration_s == 300


def test_default_journal_dir(tmp_path: Path) -> None:
    home = Path.home()
    assert (
        default_journal_dir("~/astrolol_pictures/%D", tmp_path)
        == home / "astrolol_pictures" / "journal"
    )
    assert default_journal_dir("~/pics/%O/%D", tmp_path) == home / "pics" / "journal"
    assert default_journal_dir("~/pics_%D", tmp_path) == home / "journal"
    assert default_journal_dir("%D", tmp_path) == tmp_path / "journal"
    assert default_journal_dir(None, tmp_path) == tmp_path / "journal"


def test_routes(tmp_path: Path) -> None:
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    started = {
        "type": "sequencer.session_started",
        "timestamp": "2026-09-29T21:00:00+00:00",
        "session_id": "abcdef123456",
        "actor": "user",
    }
    done = {
        "type": "sequencer.session_finished",
        "timestamp": "2026-09-29T22:00:00+00:00",
        "session_id": "abcdef123456",
        "outcome": "completed",
        "error": None,
        "frames_saved": 0,
    }
    (journal_dir / "2026-09-29_2100_abcdef123456.jsonl").write_text(
        json.dumps(started) + "\n" + json.dumps(done) + "\n"
    )
    app = FastAPI()
    app.include_router(router)
    app.state.sequencer_journal = type("J", (), {"directory": lambda self: journal_dir})()
    client = TestClient(app)
    sessions = client.get("/plugins/sequencer/sessions").json()
    assert [s["session_id"] for s in sessions] == ["abcdef123456"]
    assert sessions[0]["duration_s"] == 3600
    assert len(client.get("/plugins/sequencer/sessions/abcdef123456").json()) == 2
    assert (
        client.get("/plugins/sequencer/sessions/abcdef123456/summary").json()["outcome"]
        == "completed"
    )
    md = client.get("/plugins/sequencer/sessions/abcdef123456/export?format=md")
    assert md.status_code == 200 and "# Imaging session abcdef123456" in md.text
    assert "attachment" in md.headers["content-disposition"]
    assert client.get("/plugins/sequencer/sessions/../../etc/summary").status_code == 404
    assert client.get("/plugins/sequencer/sessions/ffffff000000/summary").status_code == 404


def test_markdown_lists_guiding_and_autofocus_events(tmp_path: Path) -> None:
    path = tmp_path / "2026-09-29_2100_abcdef123456.jsonl"
    rows = [
        {
            "type": "sequencer.session_started",
            "timestamp": "2026-09-29T21:00:00+00:00",
            "session_id": "abcdef123456",
            "actor": "user",
        },
        {
            "type": "sequencer.step_finished",
            "timestamp": "2026-09-29T21:01:00+00:00",
            "step": "autofocus",
            "duration_s": 30,
            "details": {"reason": "task start", "position": 36700},
        },
        {
            "type": "guiding.state_changed",
            "timestamp": "2026-09-29T21:10:00+00:00",
            "guider": "phd2",
            "guiding": False,
            "reason": "star_lost",
        },
        {
            "type": "guiding.state_changed",
            "timestamp": "2026-09-29T21:11:00+00:00",
            "guider": "phd2",
            "guiding": True,
            "reason": None,
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    records = read_records(path)
    md = summary_markdown(summarize(path, records), records)
    assert "autofocus (task start) → position 36700" in md
    assert "guiding interrupted: star lost" in md and "guiding (re)started" in md
