"""Mutable user settings persisted to a JSON file."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class MountDeviceSettings(BaseModel):
    """Per-mount automation settings, persisted under UserSettings.mount_settings[device_id]."""
    auto_park_enabled: bool = False
    auto_park_time: str | None = None          # "HH:MM" in local 24 h time
    auto_flip_enabled: bool = False
    auto_flip_ha_hours: float = 1.0            # hour angle threshold in decimal hours
    # How far the RA axis may turn past counterweight-horizontal, either way. Enforced by
    # drivers that implement set_meridian_limit (eqmod); INDI drivers keep their own limits.
    meridian_limit_deg: float = Field(default=20.0, ge=0.0, le=60.0)
    # Flat horizon: GOTOs below it are refused; crossing it while tracking triggers the action.
    horizon_min_alt_deg: float = Field(default=0.0, ge=-10.0, le=60.0)
    horizon_action: Literal["none", "stop_tracking", "park"] = "stop_tracking"


class UserSettings(BaseModel):
    save_dir_template: str = "~/astrolol_pictures/%D"
    save_filename_template: str = "%F_%N_%Es_%Gg"
    enabled_plugins: list[str] = []
    indi_run_dir: str = "/tmp/astrolol"       # directory for INDI FIFO and state file
    indi_local_upload: bool = False
    indi_local_upload_dir: str = "/tmp/astrolol_upload"
    low_memory_mode: bool = False
    language: str = "en"                      # UI language (BCP-47 code, e.g. "en", "fr")
    theme: str = Field(default="midnight", pattern=r"^[a-z0-9_-]{1,32}$")  # UI palette id (ui/scripts/gen-themes.mjs)
    plugin_settings: dict[str, dict] = {}     # opaque per-plugin settings, keyed by plugin id
    imager_settings: dict[str, dict] = {}     # per-device imager settings, keyed by device_id
    mount_settings: dict[str, dict] = {}      # per-device mount settings, keyed by device_id
    focuser_settings: dict[str, dict] = {}    # per-device focuser settings, keyed by device_id


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
