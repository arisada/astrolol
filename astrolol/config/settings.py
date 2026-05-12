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
    log_file: Path = _BASE / "astrolol.log"

    # INDI server settings (advanced — normally hidden in UI)
    indi_manage_server: bool = True   # False = connect to already-running server
    indi_host: str = "localhost"
    indi_port: int = 7624

    model_config = {"env_prefix": "ASTROLOL_"}


settings = Settings()
