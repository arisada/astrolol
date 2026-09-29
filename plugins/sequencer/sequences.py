"""Named sequences: reusable task plans, saved on the server or downloaded as files.

A sequence file is one JSON document holding task *definitions* (no progress, no history):

    {"format": "astrolol-sequence", "version": 1, "name": "...", "saved_at": "...",
     "tasks": [ImagingTask, ...]}

The same format is used for the server-side library (``<data dir>/sequences/``) and for
files downloaded from / uploaded by the browser, so either can go into the other.
Loading always appends fresh copies (new ids, no progress) to the queue.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, Field, ValidationError

from astrolol.core.sequencer.models import ImagingTask

logger = structlog.get_logger()

FORMAT: Literal["astrolol-sequence"] = "astrolol-sequence"


class SequenceDocument(BaseModel):
    format: Literal["astrolol-sequence"] = FORMAT
    version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=80)
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    description: str | None = Field(default=None, max_length=500)
    tasks: list[ImagingTask] = Field(min_length=1)


class SequenceInfo(BaseModel):
    id: str  # the slug: how routes address the sequence
    name: str
    saved_at: datetime
    description: str | None = None
    tasks: int
    targets: list[str]
    exposure_s: float


class SequenceExists(Exception):
    pass


class SequenceNotFound(Exception):
    pass


def slug(name: str) -> str:
    """A file name for a sequence name (the name itself is stored inside the file)."""
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s[:60] or "sequence"


def info(doc: SequenceDocument) -> SequenceInfo:
    targets: list[str] = []
    for t in doc.tasks:
        if t.target.name not in targets:
            targets.append(t.target.name)
    exposure = sum(g.count * g.duration for t in doc.tasks for lane in t.lanes for g in lane.groups)
    return SequenceInfo(
        id=slug(doc.name),
        name=doc.name,
        saved_at=doc.saved_at,
        description=doc.description,
        tasks=len(doc.tasks),
        targets=targets,
        exposure_s=exposure,
    )


def strip_ids(tasks: list[ImagingTask]) -> list[ImagingTask]:
    """Definitions only: ids are assigned again when the tasks are loaded."""
    return [
        t.model_copy(
            update={
                "id": "",
                "lanes": [lane.model_copy(update={"id": ""}) for lane in t.lanes],
            }
        )
        for t in tasks
    ]


class SequenceLibrary:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    @property
    def directory(self) -> Path:
        return self._dir

    def _path(self, name: str) -> Path:
        return self._dir / f"{slug(name)}.json"

    def _read(self, path: Path) -> SequenceDocument | None:
        try:
            return SequenceDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            logger.warning("sequencer.sequence_unreadable", path=str(path), error=str(exc))
            return None

    def list(self) -> list[SequenceInfo]:
        if not self._dir.is_dir():
            return []
        docs = [d for d in (self._read(p) for p in self._dir.glob("*.json")) if d is not None]
        return sorted((info(d) for d in docs), key=lambda i: i.name.lower())

    def get(self, name: str) -> SequenceDocument:
        path = self._path(name)
        doc = self._read(path) if path.exists() else None
        if doc is None:
            raise SequenceNotFound(name)
        return doc

    def save(self, doc: SequenceDocument, *, overwrite: bool = False) -> SequenceInfo:
        path = self._path(doc.name)
        if path.exists() and not overwrite:
            existing = self._read(path)
            raise SequenceExists(existing.name if existing else doc.name)
        doc = doc.model_copy(update={"tasks": strip_ids(doc.tasks)})
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
        logger.info("sequencer.sequence_saved", name=doc.name, tasks=len(doc.tasks), path=str(path))
        return info(doc)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.exists():
            raise SequenceNotFound(name)
        path.unlink()
        logger.info("sequencer.sequence_deleted", name=name)
