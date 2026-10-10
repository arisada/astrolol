"""QueueStore — the queue (definitions + runtime) persisted atomically to one JSON file."""

from __future__ import annotations

import json
import os
from pathlib import Path

import structlog
from pydantic import BaseModel, ValidationError

from astrolol.core.sequencer.models import QueueEntry, TaskStatus

logger = structlog.get_logger()

SCHEMA_VERSION = 2


class _QueueFile(BaseModel):
    schema_version: int = SCHEMA_VERSION
    entries: list[QueueEntry] = []


class QueueStore:
    """Loads and saves the queue. The caller owns the list; call save() after changes."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[QueueEntry]:
        """Load the queue. A task left RUNNING (crash, power loss) becomes INTERRUPTED."""
        self._delete_legacy_state()
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text())
            if raw.get("schema_version") != SCHEMA_VERSION:
                logger.warning(
                    "sequencer.queue_schema_mismatch",
                    path=str(self._path),
                    found=raw.get("schema_version"),
                )
                return []
            data = _QueueFile.model_validate(raw)
        except (OSError, ValueError, ValidationError) as exc:
            logger.error("sequencer.queue_load_failed", path=str(self._path), error=str(exc))
            return []
        for entry in data.entries:
            if entry.runtime.status == TaskStatus.RUNNING:
                entry.runtime.status = TaskStatus.INTERRUPTED
                entry.runtime.stall = None
        logger.info("sequencer.queue_loaded", path=str(self._path), tasks=len(data.entries))
        return data.entries

    def save(self, entries: list[QueueEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = _QueueFile(entries=entries).model_dump_json(indent=2)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(payload)
        os.replace(tmp, self._path)

    def _delete_legacy_state(self) -> None:
        """The v1 progress file (sequencer_state.json) can never match v2 tasks."""
        legacy = self._path.parent / "sequencer_state.json"
        if legacy.exists():
            legacy.unlink(missing_ok=True)
            logger.info("sequencer.legacy_state_deleted", path=str(legacy))
