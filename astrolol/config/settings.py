import os
from pathlib import Path
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

    # INDI server settings (advanced — normally hidden in UI)
    indi_manage_server: bool = True   # False = connect to already-running server
    indi_host: str = "localhost"
    indi_port: int = 7624

    # Extra browser origins allowed to call the API (e.g. a UI served from another
    # host). The server's own origin is always allowed. JSON list in the env var:
    # ASTROLOL_ALLOWED_ORIGINS='["https://astro.example"]'
    allowed_origins: list[str] = []

    model_config = {"env_prefix": "ASTROLOL_"}


settings = Settings()
