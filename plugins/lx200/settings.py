"""LX200 plugin settings."""
from pydantic import BaseModel


class Lx200Settings(BaseModel):
    port: int = 10001
    autostart: bool = True
