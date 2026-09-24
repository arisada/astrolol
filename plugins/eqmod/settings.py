"""EQMOD plugin settings.

Device-specific knobs that don't belong on the shared IMount contract live
here, not on astrolol/devices/base/interfaces.py — see the design discussion
referenced in plugins/eqmod/simulator.py's __init__. They're added one at a
time as the real EQMOD driver needs them; led_brightness is the first,
serving mainly as proof of the pattern (settings model -> plugin API ->
concrete adapter instance) while the simulator stands in for real hardware.
"""
from pydantic import BaseModel, Field


class EqmodSettings(BaseModel):
    led_brightness: int = Field(default=50, ge=0, le=100)
