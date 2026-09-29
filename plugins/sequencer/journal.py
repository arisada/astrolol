"""Session journal — a structured record of what happened during each run.

The standard log is for debugging; the journal is for the user: one JSONL file per run
(``<journal dir>/<YYYY-MM-DD>_<HHMM>_<session id>.jsonl``), one record per line, appended
and flushed as things happen so a crash leaves a readable file.

Records are the sequencer's own events (the same models the WebSocket carries) plus the
guider's ``guiding.*`` events during the run, and two journal-only kinds:

- ``journal.context`` — settings, equipment (optical paths) and the tasks in the run,
  written right after ``sequencer.session_started``
- ``journal.activity`` — each change of run state / activity / current task, from which
  the time breakdown is computed

The status and queue snapshots themselves are not recorded.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import IO, Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

_JOURNALED = ("sequencer.", "guiding.")
_NOT_JOURNALED = {"sequencer.status", "sequencer.queue_changed"}
_SESSION_ID = re.compile(r"^[0-9a-f]{6,32}$")


# ── Writer ────────────────────────────────────────────────────────────────────


class JournalWriter:
    """Subscribes to the event bus and writes one file per session."""

    def __init__(
        self,
        bus: Any,
        directory: Callable[[], Path],
        context: Callable[[], dict[str, Any]],
    ) -> None:
        self._bus = bus
        self._directory = directory
        self._context = context
        self._task: asyncio.Task[None] | None = None
        self._file: IO[str] | None = None
        self._path: Path | None = None
        self._last_activity: tuple[Any, ...] | None = None
        self._q: asyncio.Queue[Any] | None = None

    @property
    def current_path(self) -> Path | None:
        return self._path

    def directory(self) -> Path:
        return self._directory()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._consume(), name="sequencer_journal")

    async def stop(self) -> None:
        # Let already-published events (e.g. the session_finished of a run being shut
        # down) reach the file first.
        for _ in range(100):
            if self._q is None or self._q.empty():
                break
            await asyncio.sleep(0.01)
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._close()

    async def _consume(self) -> None:
        q = self._q = self._bus.subscribe()
        try:
            while True:
                event = await q.get()
                try:
                    await self._handle(event)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # the journal must never break a run
                    logger.warning("sequencer.journal_write_failed", error=str(exc))
        finally:
            self._bus.unsubscribe(q)
            self._q = None

    async def _handle(self, event: Any) -> None:
        etype = getattr(event, "type", "")
        if etype == "sequencer.session_started":
            await self._open(event)
            await self._write(event.model_dump(mode="json"))
            await self._write(
                {
                    "type": "journal.context",
                    "timestamp": event.model_dump(mode="json")["timestamp"],
                    **self._context(),
                }
            )
            return
        if self._file is None:
            return
        if etype == "sequencer.status":
            st = event.status
            key = (st.run_state, st.activity, st.current_task_id)
            if key != self._last_activity:
                self._last_activity = key
                await self._write(
                    {
                        "type": "journal.activity",
                        "timestamp": event.model_dump(mode="json")["timestamp"],
                        "run_state": st.run_state.value,
                        "activity": st.activity.value if st.activity else None,
                        "task_id": st.current_task_id,
                        "message": st.message,
                    }
                )
            return
        if etype in _NOT_JOURNALED or not etype.startswith(_JOURNALED):
            return
        await self._write(event.model_dump(mode="json"))
        if etype == "sequencer.session_finished":
            await self._close()

    async def _open(self, event: Any) -> None:
        await self._close()
        directory = self._directory()
        started = event.timestamp.astimezone()
        path = directory / f"{started:%Y-%m-%d_%H%M}_{event.session_id}.jsonl"

        def _mk() -> IO[str]:
            directory.mkdir(parents=True, exist_ok=True)
            return path.open("a", encoding="utf-8")

        self._file = await asyncio.to_thread(_mk)
        self._path = path
        self._last_activity = None
        logger.info("sequencer.journal_opened", path=str(path))

    async def _write(self, record: dict[str, Any]) -> None:
        f = self._file
        if f is None:
            return
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"

        def _append() -> None:
            f.write(line)
            f.flush()

        await asyncio.to_thread(_append)

    async def _close(self) -> None:
        f, self._file = self._file, None
        if f is not None:
            await asyncio.to_thread(f.close)
            logger.info("sequencer.journal_closed", path=str(self._path))


def default_journal_dir(save_dir_template: str | None, fallback: Path) -> Path:
    """'journal' in the fixed part of the image save directory template
    (``~/astrolol_pictures/%D`` → ``~/astrolol_pictures/journal``), else under *fallback*."""
    if save_dir_template:
        prefix = save_dir_template.split("%", 1)[0]
        if prefix.strip():
            base = Path(prefix).expanduser()
            if "%" in save_dir_template and not prefix.endswith("/"):
                base = base.parent  # the template cuts a directory name in half
            if str(base) not in ("", "."):
                return base / "journal"
    return fallback / "journal"


# ── Reader ────────────────────────────────────────────────────────────────────


class IntegrationRow(BaseModel):
    object_name: str
    camera_id: str | None = None
    filter_name: str | None
    frames: int
    seconds: float
    uncounted: int = 0


class TimeShare(BaseModel):
    activity: str  # exposing, slewing, …, "paused", "idle"
    seconds: float


class SessionSummary(BaseModel):
    session_id: str
    file: str
    started_at: datetime | None
    finished_at: datetime | None  # None: still running, or the process stopped
    duration_s: float
    outcome: str | None
    error: str | None = None
    actor: str | None = None
    tasks: list[str] = []
    frames_saved: int = 0
    frames_uncounted: int = 0
    frames_discarded: int = 0
    integration_s: float = 0.0
    integration: list[IntegrationRow] = []
    time: list[TimeShare] = []
    interruptions: int = 0
    stalls: int = 0
    step_failures: int = 0


def session_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.jsonl"), reverse=True)


def find_session(directory: Path, session_id: str) -> Path | None:
    if not _SESSION_ID.match(session_id):
        return None
    return next((p for p in session_files(directory) if p.stem.endswith(f"_{session_id}")), None)


def read_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line cut short by a crash
    return records


def _ts(record: dict[str, Any]) -> datetime | None:
    raw = record.get("timestamp")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def summarize(path: Path, records: list[dict[str, Any]]) -> SessionSummary:
    session_id = path.stem.rsplit("_", 1)[-1]
    started = next((r for r in records if r["type"] == "sequencer.session_started"), None)
    finished = next((r for r in records if r["type"] == "sequencer.session_finished"), None)
    context = next((r for r in records if r["type"] == "journal.context"), None)
    t0 = _ts(started) if started else (_ts(records[0]) if records else None)
    t_end = _ts(finished) if finished else (_ts(records[-1]) if records else None)

    names: dict[str, str] = {}
    for entry in (context or {}).get("tasks", []):
        task = entry.get("task", entry)
        names[task["id"]] = task.get("name") or task["target"]["name"]

    rows: dict[tuple[str, str | None, str | None], IntegrationRow] = {}
    summary = SessionSummary(
        session_id=session_id,
        file=str(path),
        started_at=t0,
        finished_at=_ts(finished) if finished else None,
        duration_s=round((t_end - t0).total_seconds(), 1) if t0 and t_end else 0.0,
        outcome=finished.get("outcome") if finished else None,
        error=finished.get("error") if finished else None,
        actor=started.get("actor") if started else None,
    )
    for r in records:
        rtype = r["type"]
        if rtype == "sequencer.frame_saved":
            obj = r.get("object_name") or names.get(r["task_id"], r["task_id"][:8])
            key = (obj, r.get("camera_id"), r.get("filter_name"))
            row = rows.setdefault(
                key,
                IntegrationRow(
                    object_name=obj, camera_id=key[1], filter_name=key[2], frames=0, seconds=0
                ),
            )
            summary.frames_saved += 1
            if r.get("counted", True):
                row.frames += 1
                row.seconds += r["duration"]
                summary.integration_s += r["duration"]
            else:
                row.uncounted += 1
                summary.frames_uncounted += 1
        elif rtype == "sequencer.frame_discarded":
            summary.frames_discarded += 1
        elif rtype == "sequencer.interruption":
            summary.interruptions += 1
        elif rtype == "sequencer.task_stalled":
            summary.stalls += 1
        elif rtype == "sequencer.step_failed":
            summary.step_failures += 1
        elif rtype == "sequencer.task_started":
            name = r.get("name") or names.get(r["task_id"], "")
            if name and name not in summary.tasks:
                summary.tasks.append(name)
    summary.integration = sorted(
        rows.values(), key=lambda row: (row.object_name, row.camera_id or "", row.filter_name or "")
    )
    summary.integration_s = round(summary.integration_s, 1)
    summary.time = time_breakdown(records, t_end)
    return summary


def activity_label(run_state: str | None, activity: str | None) -> str:
    if run_state == "paused":
        return "paused"
    if activity:
        return activity
    return "idle" if run_state in (None, "idle") else "other"


def time_breakdown(records: list[dict[str, Any]], t_end: datetime | None) -> list[TimeShare]:
    """Seconds per activity, from the journal.activity transitions."""
    marks = [
        (_ts(r), activity_label(r.get("run_state"), r.get("activity")))
        for r in records
        if r["type"] == "journal.activity"
    ]
    marks = [(t, label) for t, label in marks if t is not None]
    if not marks:
        return []
    totals: dict[str, float] = {}
    for (t, label), nxt in zip(marks, [*marks[1:], (t_end, None)], strict=True):
        end = nxt[0] or t
        if end is None or t is None:
            continue
        totals[label] = totals.get(label, 0.0) + max(0.0, (end - t).total_seconds())
    return sorted(
        (TimeShare(activity=k, seconds=round(v, 1)) for k, v in totals.items() if v > 0),
        key=lambda s: -s.seconds,
    )


# ── Exports ───────────────────────────────────────────────────────────────────

FRAME_COLUMNS = [
    "timestamp",
    "object_name",
    "camera_id",
    "filter_name",
    "duration",
    "counted",
    "guide_rms_total",
    "unguided_s",
    "guiding_losses",
    "altitude",
    "hour_angle",
    "focuser_position",
    "sensor_temperature",
    "fits_path",
]


def frames_csv(records: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FRAME_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        if r["type"] == "sequencer.frame_saved":
            writer.writerow({k: r.get(k) for k in FRAME_COLUMNS})
    return out.getvalue()


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    return (
        f"{s // 3600}h{(s % 3600) // 60:02d}m{s % 60:02d}s"
        if s >= 3600
        else f"{s // 60}m{s % 60:02d}s"
    )


def summary_markdown(summary: SessionSummary, records: list[dict[str, Any]]) -> str:
    def local(d: datetime) -> str:
        return d.astimezone().strftime("%Y-%m-%d %H:%M")

    lines = [f"# Imaging session {summary.session_id}", ""]
    if summary.started_at:
        end = local(summary.finished_at) if summary.finished_at else "(not finished)"
        lines.append(
            f"- **When:** {local(summary.started_at)} → {end} ({_hms(summary.duration_s)})"
        )
    lines.append(
        f"- **Outcome:** {summary.outcome or 'unknown'}"
        + (f" — {summary.error}" if summary.error else "")
    )
    lines.append(f"- **Tasks:** {', '.join(summary.tasks) or '—'}")
    lines.append(
        f"- **Frames:** {summary.frames_saved} saved ({summary.frames_uncounted} not counted), "
        f"{summary.frames_discarded} discarded — {_hms(summary.integration_s)} integration"
    )
    lines.append(
        f"- **Interruptions:** {summary.interruptions} · **stalls:** {summary.stalls} "
        f"· **failed steps:** {summary.step_failures}"
    )
    lines += [
        "",
        "## Integration",
        "",
        "| Target | Camera | Filter | Frames | Time | Not counted |",
        "|---|---|---|---|---|---|",
    ]
    for row in summary.integration:
        cells = [
            row.object_name,
            row.camera_id or "—",
            row.filter_name or "—",
            row.frames,
            _hms(row.seconds),
            row.uncounted,
        ]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    lines += ["", "## Where the time went", "", "| Activity | Time | Share |", "|---|---|---|"]
    total = sum(t.seconds for t in summary.time) or 1.0
    for t in (t for t in summary.time if t.seconds >= 1):
        share = f"{100 * t.seconds / total:.0f} %"
        lines.append(f"| {t.activity.replace('_', ' ')} | {_hms(t.seconds)} | {share} |")
    notable = [r for r in records if _notable(r)]
    if notable:
        lines += ["", "## Events", ""]
        for r in notable:
            ts = _ts(r)
            when = ts.astimezone().strftime("%H:%M:%S") if ts else "?"
            lines.append(f"- {when} — {_describe(r)}")
    return "\n".join(lines) + "\n"


_NOTABLE = {
    "sequencer.interruption",
    "sequencer.resumed",
    "sequencer.task_stalled",
    "sequencer.task_unstalled",
    "sequencer.step_failed",
    "sequencer.task_finished",
    "guiding.state_changed",
}
_NOTABLE_STEPS = {"autofocus", "center", "meridian_flip"}


def _notable(r: dict[str, Any]) -> bool:
    return r["type"] in _NOTABLE or (
        r["type"] == "sequencer.step_finished" and r.get("step") in _NOTABLE_STEPS
    )


def _describe(r: dict[str, Any]) -> str:
    t = r["type"]
    details = r.get("details") or {}
    if t == "guiding.state_changed":
        if r.get("guiding"):
            return "guiding (re)started"
        return f"guiding interrupted: {str(r.get('reason') or '').replace('_', ' ')}"
    if t == "sequencer.resumed":
        return f"resumed after {_hms(r['paused_s'])}" + (
            " (setup re-run)" if r.get("setup_rerun") else ""
        )
    if t == "sequencer.step_finished":
        if r.get("step") == "autofocus":
            return f"autofocus ({details.get('reason')}) → position {details.get('position')}"
        if r.get("step") == "center":
            return (
                f"centered in {details.get('attempts')} attempt(s), "
                f"{details.get('final_error_arcsec')}″ off"
            )
        return f"meridian flip ({details.get('pier_before')} → {details.get('pier_after')})"
    if t == "sequencer.interruption":
        return f"{r['kind']} by {r['actor']}" + (f": {r['reason']}" if r.get("reason") else "")
    if t == "sequencer.task_stalled":
        return f"{r['kind']} stalled: {r['error']}"
    if t == "sequencer.task_unstalled":
        return f"{r['kind']} recovered after {_hms(r['duration_s'])} ({r['attempts']} attempts)"
    if t == "sequencer.step_failed":
        return f"{r['step']} failed ({r['handling']}): {r['error']}"
    if t == "sequencer.task_finished":
        return f"task {r['status']}" + (f": {r['error']}" if r.get("error") else "")
    return str(t)
