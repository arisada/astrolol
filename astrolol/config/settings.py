"""astrolol's start-up configuration.

Read once when astrolol starts, from (highest priority first):
  1. ASTROLOL_<FIELD> environment variables,
  2. the configuration file CONFIG_FILE (TOML, one `field = value` per line; optional),
  3. the defaults below.
What the user changes in the UI is not here: it lives in UserSettings, in the data directory.
"""
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# A system-wide install ships this file (the Debian package sets data_dir in it). ASTROLOL_CONFIG
# names another one; the tests point it at a file that does not exist.
CONFIG_FILE = Path(os.environ.get("ASTROLOL_CONFIG", "/etc/astrolol/astrolol.toml"))


def _in_data_dir(name: str) -> Any:
    """Default to a path inside data_dir (as configured, so it follows a data_dir from the file)."""
    return Field(default_factory=lambda data: data["data_dir"] / name)


class Settings(BaseSettings):
    # Settings, profiles, users, logs; each file below can still be moved on its own.
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".astrolol")
    images_dir: Path = _in_data_dir("images")
    jpeg_quality: int = 85
    profiles_file: Path = _in_data_dir("profiles.json")
    inventory_file: Path = _in_data_dir("inventory.json")
    bluetooth_devices_file: Path = _in_data_dir("bluetooth_devices.json")
    log_file: Path = _in_data_dir("astrolol.log")
    security_file: Path = _in_data_dir("security.json")  # users, API tokens, sessions (security plugin)
    service_token_file: Path = _in_data_dir("service_token")  # credential for astrolol's own helper processes
    # The built web UI (ui/dist), when it is not found next to the code.
    ui_dist: Path | None = None

    # INDI server settings; Options sets them too (UserSettings.indi_server), the configuration wins.
    indi_manage_server: bool = True   # False = connect to already-running server
    indi_host: str = "localhost"
    indi_port: int = 7624
    # Which server speaks INDI to astrolol: "indi" (indiserver) or "indigo" (indigo_server).
    indi_server_kind: Literal["indi", "indigo"] = "indi"
    indigo_server_path: str = "indigo_server"   # name on PATH, or a full path

    # Extra browser origins allowed to call the API (e.g. a UI served from another
    # host). The server's own origin is always allowed. JSON list in the env var:
    # ASTROLOL_ALLOWED_ORIGINS='["https://astro.example"]'
    allowed_origins: list[str] = []

    model_config = SettingsConfigDict(env_prefix="ASTROLOL_", toml_file=CONFIG_FILE)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, env_settings, TomlConfigSettingsSource(settings_cls)


settings = Settings()

# The fields of the INDI server choice (UserSettings.indi_server) and the settings they set.
INDI_SERVER_FIELDS = {
    "kind": "indi_server_kind",
    "managed": "indi_manage_server",
    "host": "indi_host",
    "port": "indi_port",
    "indigo_path": "indigo_server_path",
}
# Settings the start-up configuration set (file or environment): they win over the choice made
# in Options.
CONFIGURED_FIELDS = frozenset(settings.model_fields_set)


def indi_server_configured_keys() -> list[str]:
    """The keys of the INDI server choice fixed by the start-up configuration."""
    return [key for key, field in INDI_SERVER_FIELDS.items() if field in CONFIGURED_FIELDS]


def apply_indi_server_choice(choice: object) -> None:
    """Use the INDI server chosen in Options (read at start), except what the configuration sets."""
    for key, field in INDI_SERVER_FIELDS.items():
        value = getattr(choice, key, None)
        if value is not None and field not in CONFIGURED_FIELDS:
            setattr(settings, field, value)
