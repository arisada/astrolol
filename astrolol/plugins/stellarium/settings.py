"""Stellarium plugin settings."""
from pydantic import BaseModel


class StellariumSettings(BaseModel):
    port: int = 10002
    autostart: bool = True
