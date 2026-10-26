"""Alpaca plugin settings."""
from pydantic import BaseModel, Field


class AlpacaSettings(BaseModel):
    # Servers asked directly at every scan (discovery does not reach them: another subnet,
    # a VPN), as "host" or "host:port".
    addresses: list[str] = Field(default_factory=list, max_length=20)
