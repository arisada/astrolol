"""Mutable user settings persisted to a JSON file."""
from __future__ import annotations

import json
from pathlib import Path

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class UserSettings(BaseModel):
    save_dir_template: str = "~/astrolol_pictures/%D"
    save_filename_template: str = "%F_%C_%Es_%Gg"
    enabled_plugins: list[str] = []
    phd2_host: str = "localhost"
    phd2_port: int = 4400
    astap_db_path: str = "/opt/astap"   # directory containing the star database
    astap_bin: str = "astap_cli"              # path or name of the astap_cli executable
    astap_search_radius: float = 30.0         # degrees; passed as -r to astap_cli
    astap_tolerance: float = 0.007            # star-match tolerance; passed as -t to astap_cli
    pixel_size_um: float | None = None        # sensor pixel size in µm; used to hint FOV
    indi_run_dir: str = "/tmp/astrolol"       # directory for INDI FIFO and state file
    lx200_port: int = 10001                   # TCP port for the LX200 server
    lx200_autostart: bool = True              # start LX200 server when plugin is enabled
    stellarium_port: int = 10002              # TCP port for the Stellarium server
    stellarium_autostart: bool = True         # start Stellarium server when plugin is enabled


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
