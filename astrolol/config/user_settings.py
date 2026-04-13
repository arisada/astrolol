"""Mutable user settings persisted to a JSON file."""
from __future__ import annotations

import json
from pathlib import Path

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class UserSettings(BaseModel):
    save_dir_template: str = "~/Pictures/astrolol/%D"
    save_filename_template: str = "%F_%C_%Es_%Gg"


class UserSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._settings = self._load()

    def _load(self) -> UserSettings:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                return UserSettings(**data)
            except Exception as exc:
                logger.warning("user_settings.load_failed", path=str(self._path), error=str(exc))
        return UserSettings()

    def get(self) -> UserSettings:
        return self._settings

    def update(self, settings: UserSettings) -> UserSettings:
        self._settings = settings
        self._path.write_text(settings.model_dump_json(indent=2))
        return self._settings
