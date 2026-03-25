from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    images_dir: Path = Path("./images")
    jpeg_quality: int = 85

    # INDI server settings (advanced — normally hidden in UI)
    indi_manage_server: bool = True   # False = connect to already-running server
    indi_host: str = "localhost"
    indi_port: int = 7624

    model_config = {"env_prefix": "ASTROLOL_"}


settings = Settings()
