from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    images_dir: Path = Path("./images")
    jpeg_quality: int = 85

    model_config = {"env_prefix": "ASTROLOL_"}


settings = Settings()
