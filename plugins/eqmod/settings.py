"""EQMOD plugin settings.

Device-specific knobs that don't belong on the shared IMount contract, plus the INDI
mount proxy (exposes astrolol's mount to INDI clients such as PHD2 and to drivers
that snoop a telescope).
"""
from pydantic import BaseModel, Field


class EqmodSettings(BaseModel):
    led_brightness: int = Field(default=50, ge=0, le=100)
    indi_proxy_enabled: bool = False
    # Where the proxy (run by indiserver on this machine) reaches astrolol's REST API.
    indi_proxy_api_url: str = Field(default="http://127.0.0.1:8000", pattern=r"^https?://")
