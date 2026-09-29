"""REST routes for the sequencer — a thin layer over ``app.state.sequencer``.

The router depends only on the core ``Sequencer`` protocol, not on this plugin's
implementation, except for the settings routes (settings are implementation-specific).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from astrolol.core.sequencer import (
    Boundary,
    ImagingTask,
    InvalidRequest,
    PreflightFailed,
    PreflightReport,
    QueueEntry,
    Sequencer,
    SequencerBusy,
    SequencerNotRunning,
    SequencerStatus,
    TaskLocked,
    TaskNotFound,
)
from plugins.sequencer.journal import (
    SessionSummary,
    find_session,
    frames_csv,
    read_records,
    session_files,
    summarize,
    summary_markdown,
)
from plugins.sequencer.lanes import LaneEstimate
from plugins.sequencer.sequences import (
    SequenceDocument,
    SequenceExists,
    SequenceInfo,
    SequenceLibrary,
    SequenceNotFound,
    slug,
    strip_ids,
)
from plugins.sequencer.settings import SequencerSettings

logger = structlog.get_logger()
router = APIRouter(prefix="/plugins/sequencer", tags=["sequencer"])

T = TypeVar("T")


def _seq(request: Request) -> Sequencer:
    return request.app.state.sequencer  # type: ignore[no-any-return]


async def _call(fn: Callable[[], Awaitable[T]]) -> T:
    """Run a service call, mapping sequencer errors to HTTP status codes."""
    try:
        return await fn()
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TaskLocked, SequencerBusy) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (InvalidRequest, SequencerNotRunning) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PreflightFailed as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "report": exc.report.model_dump(mode="json")},
        ) from exc


class ActorBody(BaseModel):
    actor: str = "user"
    reason: str | None = None


# ── Queue ─────────────────────────────────────────────────────────────────────


@router.get("/queue", response_model=list[QueueEntry])
async def get_queue(request: Request) -> list[QueueEntry]:
    return await _seq(request).list_tasks()


@router.post("/queue", status_code=201, response_model=QueueEntry)
async def add_task(task: ImagingTask, request: Request, position: int | None = None) -> QueueEntry:
    return await _call(lambda: _seq(request).add(task, position=position))


@router.post("/queue/insert_next", status_code=201, response_model=QueueEntry)
async def insert_next(task: ImagingTask, request: Request) -> QueueEntry:
    return await _call(lambda: _seq(request).insert_next(task))


class ReorderBody(BaseModel):
    order: list[str]


@router.post("/queue/reorder", status_code=204)
async def reorder(body: ReorderBody, request: Request) -> None:
    await _call(lambda: _seq(request).reorder(body.order))


_Clearable = Literal["pending", "interrupted", "completed", "failed", "skipped"]


@router.delete("/queue", status_code=204)
async def clear_queue(
    request: Request,
    status: Annotated[list[_Clearable], Query()] = ["completed", "skipped"],  # noqa: B006
) -> None:
    await _call(lambda: _seq(request).clear(list(status)))


@router.get("/queue/{task_id}", response_model=QueueEntry)
async def get_task(task_id: str, request: Request) -> QueueEntry:
    return await _call(lambda: _seq(request).get(task_id))


@router.put("/queue/{task_id}", response_model=QueueEntry)
async def update_task(task_id: str, task: ImagingTask, request: Request) -> QueueEntry:
    return await _call(lambda: _seq(request).update(task_id, task))


@router.delete("/queue/{task_id}", status_code=204)
async def remove_task(task_id: str, request: Request) -> None:
    await _call(lambda: _seq(request).remove(task_id))


@router.post("/queue/{task_id}/duplicate", status_code=201, response_model=QueueEntry)
async def duplicate_task(task_id: str, request: Request) -> QueueEntry:
    return await _call(lambda: _seq(request).duplicate(task_id))


@router.post("/queue/{task_id}/reset_progress", response_model=QueueEntry)
async def reset_progress(task_id: str, request: Request) -> QueueEntry:
    return await _call(lambda: _seq(request).reset_progress(task_id))


@router.post("/queue/{task_id}/skip", response_model=QueueEntry)
async def skip_task(task_id: str, request: Request, body: ActorBody | None = None) -> QueueEntry:
    seq = _seq(request)
    actor = body.actor if body else "user"
    if seq.status().current_task_id == task_id:
        await _call(lambda: seq.skip_current("frame", actor=actor))
        return await _call(lambda: seq.get(task_id))
    return await _call(lambda: seq.set_status(task_id, "skipped", actor=actor))


@router.post("/queue/{task_id}/unskip", response_model=QueueEntry)
async def unskip_task(task_id: str, request: Request, body: ActorBody | None = None) -> QueueEntry:
    actor = body.actor if body else "user"
    return await _call(lambda: _seq(request).set_status(task_id, "pending", actor=actor))


# ── Control ───────────────────────────────────────────────────────────────────


class PreflightBody(BaseModel):
    task_ids: list[str] | None = None


@router.post("/preflight", response_model=PreflightReport)
async def preflight(request: Request, body: PreflightBody | None = None) -> PreflightReport:
    return await _call(lambda: _seq(request).preflight(body.task_ids if body else None))


@router.post("/estimate", response_model=list[LaneEstimate])
async def estimate(task: ImagingTask, request: Request) -> list[LaneEstimate]:
    """Per-lane exposure time, efficiency and duration for a task definition (editor aid)."""
    return request.app.state.sequencer.estimate(task)  # type: ignore[no-any-return]


class StartBody(BaseModel):
    from_task: str | None = None
    only: list[str] | None = None
    actor: str = "user"


@router.post("/start", status_code=202)
async def start(request: Request, body: StartBody | None = None) -> dict[str, str]:
    b = body or StartBody()
    await _call(lambda: _seq(request).start(from_task=b.from_task, only=b.only, actor=b.actor))
    return {"status": "started"}


@router.post("/pause", status_code=204)
async def pause(request: Request, when: Boundary = "frame", body: ActorBody | None = None) -> None:
    actor = body.actor if body else "user"
    await _call(lambda: _seq(request).pause(when, actor=actor))


@router.post("/resume", status_code=204)
async def resume(request: Request, body: ActorBody | None = None) -> None:
    actor = body.actor if body else "user"
    await _call(lambda: _seq(request).resume(actor=actor))


@router.post("/stop", status_code=204)
async def stop(request: Request, when: Boundary = "frame", body: ActorBody | None = None) -> None:
    b = body or ActorBody()
    await _call(lambda: _seq(request).stop(when, actor=b.actor, reason=b.reason))


@router.post("/skip_current", status_code=204)
async def skip_current(
    request: Request, when: Boundary = "frame", body: ActorBody | None = None
) -> None:
    actor = body.actor if body else "user"
    await _call(lambda: _seq(request).skip_current(when, actor=actor))


class SwitchBody(BaseModel):
    task_id: str
    when: Boundary = "frame"
    actor: str = "user"
    reason: str | None = None


@router.post("/switch", status_code=204)
async def switch(body: SwitchBody, request: Request) -> None:
    await _call(
        lambda: _seq(request).switch_to(
            body.task_id, body.when, actor=body.actor, reason=body.reason
        )
    )


# ── Status & settings ─────────────────────────────────────────────────────────


@router.get("/status", response_model=SequencerStatus)
async def get_status(request: Request) -> SequencerStatus:
    return _seq(request).status()


@router.get("/settings", response_model=SequencerSettings)
async def get_settings(request: Request) -> SequencerSettings:
    return request.app.state.sequencer.settings  # type: ignore[no-any-return]


@router.put("/settings", response_model=SequencerSettings)
async def put_settings(body: SequencerSettings, request: Request) -> SequencerSettings:
    request.app.state.sequencer.update_settings(body)
    store = getattr(request.app.state, "profile_store", None)
    if store is not None:
        current = store.get_user_settings()
        updated = {**current.plugin_settings, "sequencer": body.model_dump()}
        store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    logger.info("sequencer.settings_updated")
    return body


# ── Session journal ───────────────────────────────────────────────────────────


def _journal_dir(request: Request) -> Path:
    journal = getattr(request.app.state, "sequencer_journal", None)
    if journal is None:
        raise HTTPException(status_code=404, detail="The session journal is not available")
    return journal.directory()  # type: ignore[no-any-return]


def _session(request: Request, session_id: str) -> tuple[Path, list[dict[str, Any]]]:
    path = find_session(_journal_dir(request), session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return path, read_records(path)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    request: Request, limit: int = Query(default=50, ge=1, le=500)
) -> list[SessionSummary]:
    """Past runs, newest first."""
    directory = _journal_dir(request)

    def _load() -> list[SessionSummary]:
        return [summarize(p, read_records(p)) for p in session_files(directory)[:limit]]

    return await asyncio.to_thread(_load)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> list[dict[str, Any]]:
    """Every journal record of a session."""
    _, records = await asyncio.to_thread(_session, request, session_id)
    return records


@router.get("/sessions/{session_id}/summary", response_model=SessionSummary)
async def get_session_summary(session_id: str, request: Request) -> SessionSummary:
    path, records = await asyncio.to_thread(_session, request, session_id)
    return summarize(path, records)


@router.get("/sessions/{session_id}/export")
async def export_session(
    session_id: str, request: Request, format: Literal["csv", "md"] = "md"
) -> PlainTextResponse:
    """Frames as CSV, or a Markdown report."""
    path, records = await asyncio.to_thread(_session, request, session_id)
    if format == "csv":
        body, media, ext = frames_csv(records), "text/csv", "csv"
    else:
        body, media, ext = (
            summary_markdown(summarize(path, records), records),
            "text/markdown",
            "md",
        )
    return PlainTextResponse(
        body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{path.stem}.{ext}"'},
    )


# ── Named sequences and file import/export ────────────────────────────────────


def _library(request: Request) -> SequenceLibrary:
    library = getattr(request.app.state, "sequencer_library", None)
    if library is None:
        raise HTTPException(status_code=404, detail="The sequence library is not available")
    return library  # type: ignore[no-any-return]


async def _append(request: Request, tasks: list[ImagingTask]) -> list[QueueEntry]:
    seq = _seq(request)
    return [await seq.add(t) for t in tasks]


async def _document(
    request: Request, name: str, task_ids: list[str] | None, include_completed: bool = True
) -> SequenceDocument:
    entries = await _seq(request).list_tasks()
    if task_ids is not None:
        wanted = set(task_ids)
        missing = wanted - {e.task.id for e in entries}
        if missing:
            raise HTTPException(
                status_code=404, detail=f"Task(s) not found: {', '.join(sorted(missing))}"
            )
        entries = [e for e in entries if e.task.id in wanted]
    if not include_completed:
        entries = [e for e in entries if e.runtime.status != "completed"]
    if not entries:
        raise HTTPException(status_code=422, detail="No task to save")
    return SequenceDocument(name=name, tasks=[e.task for e in entries])


@router.get("/export", response_model=SequenceDocument)
async def export_queue(
    request: Request,
    ids: Annotated[list[str] | None, Query()] = None,
    name: str | None = None,
) -> JSONResponse:
    """Download tasks (all, or the given ids) as a sequence file."""
    entries = await _seq(request).list_tasks()
    default = next((e.task.display_name for e in entries if ids and e.task.id == ids[0]), None)
    title = name or (default if ids and len(ids) == 1 else "astrolol queue")
    doc = await _document(request, title or "astrolol queue", ids)
    doc = doc.model_copy(update={"tasks": strip_ids(doc.tasks)})
    return JSONResponse(
        doc.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="{slug(doc.name)}.json"'},
    )


@router.post("/import", status_code=201, response_model=list[QueueEntry])
async def import_tasks(doc: SequenceDocument, request: Request) -> list[QueueEntry]:
    """Append the tasks of an uploaded sequence file to the queue (fresh copies)."""
    return await _append(request, doc.tasks)


@router.get("/sequences", response_model=list[SequenceInfo])
async def list_sequences(request: Request) -> list[SequenceInfo]:
    library = _library(request)
    return await asyncio.to_thread(library.list)


class SaveSequenceBody(BaseModel):
    name: str
    description: str | None = None
    task_ids: list[str] | None = None  # None = the whole queue
    include_completed: bool = True
    overwrite: bool = False


@router.post("/sequences", status_code=201, response_model=SequenceInfo)
async def save_sequence(body: SaveSequenceBody, request: Request) -> SequenceInfo:
    """Save queue tasks (definitions only) as a named sequence. 409 if the name exists."""
    doc = await _document(request, body.name.strip(), body.task_ids, body.include_completed)
    doc = doc.model_copy(update={"description": body.description})
    try:
        return await asyncio.to_thread(_library(request).save, doc, overwrite=body.overwrite)
    except SequenceExists as exc:
        raise HTTPException(
            status_code=409, detail=f"A sequence named '{exc}' already exists"
        ) from exc


@router.put("/sequences", status_code=201, response_model=SequenceInfo)
async def upload_sequence(
    doc: SequenceDocument, request: Request, overwrite: bool = False
) -> SequenceInfo:
    """Store an uploaded sequence file in the library."""
    try:
        return await asyncio.to_thread(_library(request).save, doc, overwrite=overwrite)
    except SequenceExists as exc:
        raise HTTPException(
            status_code=409, detail=f"A sequence named '{exc}' already exists"
        ) from exc


def _get_sequence(request: Request, name: str) -> SequenceDocument:
    try:
        return _library(request).get(name)
    except SequenceNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Sequence '{name}' not found") from exc


@router.get("/sequences/{name}", response_model=SequenceDocument)
async def get_sequence(name: str, request: Request) -> JSONResponse:
    doc = await asyncio.to_thread(_get_sequence, request, name)
    return JSONResponse(
        doc.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="{slug(doc.name)}.json"'},
    )


@router.delete("/sequences/{name}", status_code=204)
async def delete_sequence(name: str, request: Request) -> None:
    try:
        await asyncio.to_thread(_library(request).delete, name)
    except SequenceNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Sequence '{name}' not found") from exc


@router.post("/sequences/{name}/load", status_code=201, response_model=list[QueueEntry])
async def load_sequence(name: str, request: Request) -> list[QueueEntry]:
    """Append the sequence's tasks to the queue as fresh tasks (new ids, no progress)."""
    doc = await asyncio.to_thread(_get_sequence, request, name)
    return await _append(request, doc.tasks)
