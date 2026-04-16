from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

# Allowed characters: start with alphanumeric, then alphanumeric / hyphen / underscore, max 64
_DEVICE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _friendly_id(kind: str, params: dict[str, Any]) -> str:
    """Derive a human-readable device ID from kind + INDI params.

    Priority: device_name > executable stem > random fallback.
    Examples:
      kind=focuser, device_name="ZWO Focuser"    → "focuser_zwo_focuser"
      kind=mount,   executable="indi_eqmod_telescope" → "mount_eqmod_telescope"
      kind=camera,  executable="indi_asi_ccd"    → "camera_asi_ccd"
    """
    device_name: str = str(params.get("device_name", ""))
    executable: str = str(params.get("executable", ""))

    raw = device_name or executable.removeprefix("indi_")
    slug = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")[:40]

    if slug:
        return f"{kind}_{slug}"
    return f"{kind}_{uuid4().hex[:8]}"


class DeviceConfig(BaseModel):
    device_id: str = Field(
        default="",
        description=(
            "Unique ID for this device instance. "
            "Auto-generated from the driver name when blank. "
            "Must start with a letter or digit; may contain letters, digits, hyphens, "
            "and underscores; max 64 characters. Example: 'main_camera'."
        ),
    )
    driver_name: str | None = Field(
        default=None,
        description=(
            "Physical INDI driver name when this device was auto-discovered from a "
            "multi-role driver. Example: 'CCD Simulator'."
        ),
    )
    kind: str = Field(description="Device type: 'camera' | 'mount' | 'focuser' | 'filter_wheel' | 'rotator' | 'indi'")
    adapter_key: str = Field(description="Adapter registered by a plugin, e.g. 'indi_camera'")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Adapter-specific connection parameters (e.g. INDI device name, host, port).",
    )

    @model_validator(mode="after")
    def _normalise_device_id(self) -> "DeviceConfig":
        if not self.device_id:
            # Auto-generate a friendly name from the driver info
            self.device_id = _friendly_id(self.kind, self.params)
        elif not _DEVICE_ID_RE.match(self.device_id):
            raise ValueError(
                "device_id must start with a letter or digit and contain only "
                "letters, digits, hyphens, and underscores (max 64 characters). "
                f"Got: {self.device_id!r}"
            )
        return self
