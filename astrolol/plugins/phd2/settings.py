"""PHD2 plugin settings."""
from pydantic import BaseModel


class Phd2Settings(BaseModel):
    host: str = "localhost"
    port: int = 4400
