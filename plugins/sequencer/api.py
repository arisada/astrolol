"""FastAPI router for the sequencer plugin."""
from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from plugins.sequencer.models import ImagingTask, SequencerStatus
from plugins.sequencer.runner import SequenceRunner
from plugins.sequencer.settings import SequencerSettings

logger = structlog.get_logger()
router = APIRouter(prefix="/plugins/sequencer", tags=["sequencer"])


def _runner(request: Request) -> SequenceRunner:
    return request.app.state.sequence_runner  # type: ignore[no-any-return]


# ── Queue management ──────────────────────────────────────────────────────────

@router.get("/queue", response_model=list[ImagingTask])
async def get_queue(request: Request) -> list[ImagingTask]:
    """Return the full queue (pending, running, and completed tasks)."""
    return _runner(request).list_tasks()


@router.post("/queue", status_code=201, response_model=ImagingTask)
async def add_task(task: ImagingTask, request: Request) -> ImagingTask:
    """Append a task to the queue. The server assigns a UUID if not provided."""
    # Always generate a fresh ID to prevent client-supplied UUID conflicts
    import uuid
    task = task.model_copy(update={"id": str(uuid.uuid4())})
    _runner(request).add_task(task)
    logger.info("sequencer.task_added", task_id=task.id, name=task.name)
    return task


@router.put("/queue/{task_id}", response_model=ImagingTask)
async def update_task(task_id: str, task: ImagingTask, request: Request) -> ImagingTask:
    """Replace a task (full update). Returns 409 if the task is currently running."""
    task = task.model_copy(update={"id": task_id})
    try:
        return _runner(request).update_task(task_id, task)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/queue/{task_id}", status_code=204)
async def delete_task(task_id: str, request: Request) -> None:
    """Remove a task from the queue. Returns 409 if the task is currently running."""
    try:
        _runner(request).delete_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


class ReorderBody(BaseModel):
    order: list[str]


@router.post("/queue/reorder", status_code=204)
async def reorder_queue(body: ReorderBody, request: Request) -> None:
    """Reorder pending tasks. Non-pending tasks are unaffected."""
    _runner(request).reorder_tasks(body.order)


@router.delete("/queue", status_code=204)
async def clear_queue(request: Request) -> None:
    """Remove all pending (non-running, non-completed) tasks."""
    _runner(request).clear_pending()


# ── Control ───────────────────────────────────────────────────────────────────

@router.post("/start", status_code=202)
async def start(request: Request) -> dict:
    """Start the sequencer. Returns 409 if already running."""
    runner = _runner(request)
    try:
        await runner.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    logger.info("sequencer.started")
    return {"status": "started"}


@router.post("/pause", status_code=204)
async def pause(
    request: Request,
    mode: Annotated[str, Query()] = "after_frame",
) -> None:
    """Request a pause. mode = 'after_frame' (default) | 'after_task'."""
    if mode not in ("after_frame", "after_task"):
        raise HTTPException(status_code=422, detail="mode must be 'after_frame' or 'after_task'")
    _runner(request).request_pause(mode)
    logger.info("sequencer.pause_requested", mode=mode)


@router.post("/resume", status_code=204)
async def resume(request: Request) -> None:
    """Resume after a pause."""
    _runner(request).resume()
    logger.info("sequencer.resumed")


@router.post("/cancel", status_code=204)
async def cancel(request: Request) -> None:
    """Cancel the running sequence."""
    await _runner(request).cancel()
    logger.info("sequencer.cancelled")


@router.post("/reset", status_code=204)
async def reset(request: Request) -> None:
    """Stop the runner, remove completed tasks, and delete the progress file."""
    await _runner(request).reset()
    logger.info("sequencer.reset")


# ── Status & settings ─────────────────────────────────────────────────────────

@router.get("/status", response_model=SequencerStatus)
async def get_status(request: Request) -> SequencerStatus:
    """Return current sequencer state and progress."""
    return _runner(request).get_status()


@router.get("/settings", response_model=SequencerSettings)
async def get_settings(request: Request) -> SequencerSettings:
    """Return current sequencer settings."""
    return _runner(request)._settings


@router.put("/settings", response_model=SequencerSettings)
async def put_settings(settings: SequencerSettings, request: Request) -> SequencerSettings:
    """Update sequencer settings (persisted to profile store)."""
    runner = _runner(request)
    runner.update_settings(settings)

    # Persist via profile store if available
    store = getattr(request.app.state, "profile_store", None)
    if store is not None:
        current = store.get_user_settings()
        new_ps = {**current.plugin_settings, "sequencer": settings.model_dump()}
        store.update_user_settings(current.model_copy(update={"plugin_settings": new_ps}))

    logger.info("sequencer.settings_updated")
    return settings
