import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


def _data_dir() -> Path:
    """Return the base directory for config/state files.

    Resolved once at import time from ASTROLOL_DATA_DIR (if set) or ~/.astrolol/.
    Individual file paths below inherit this value as their default but can still
    be overridden independently via their own ASTROLOL_* env vars.
    """
    env = os.environ.get("ASTROLOL_DATA_DIR")
    return Path(env) if env else Path.home() / ".astrolol"


_BASE = _data_dir()


class Settings(BaseSettings):
    images_dir: Path = Path("./images")
    jpeg_quality: int = 85
    profiles_file: Path = _BASE / "profiles.json"
    inventory_file: Path = _BASE / "inventory.json"
    bluetooth_devices_file: Path = _BASE / "bluetooth_devices.json"
    log_file: Path = _BASE / "astrolol.log"
    security_file: Path = _BASE / "security.json"       # users, API tokens, sessions (security plugin)
    service_token_file: Path = _BASE / "service_token"  # credential for astrolol's own helper processes

    # INDI server settings; Options sets them too (UserSettings.indi_server), the environment wins.
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

    model_config = {"env_prefix": "ASTROLOL_"}


settings = Settings()

# The fields of the INDI server choice (UserSettings.indi_server) and the settings they set.
INDI_SERVER_FIELDS = {
    "kind": "indi_server_kind",
    "managed": "indi_manage_server",
    "host": "indi_host",
    "port": "indi_port",
    "indigo_path": "indigo_server_path",
}
# Settings the environment set (ASTROLOL_*): they win over the choice made in Options.
ENV_FIELDS = frozenset(settings.model_fields_set)


def indi_server_env_keys() -> list[str]:
    """The keys of the INDI server choice fixed by the environment."""
    return [key for key, field in INDI_SERVER_FIELDS.items() if field in ENV_FIELDS]


def apply_indi_server_choice(choice: object) -> None:
    """Use the INDI server chosen in Options (read at start), except what the environment sets."""
    for key, field in INDI_SERVER_FIELDS.items():
        value = getattr(choice, key, None)
        if value is not None and field not in ENV_FIELDS:
            setattr(settings, field, value)
