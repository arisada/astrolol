from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field


class DeviceConfig(BaseModel):
    device_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique ID for this device instance. Set explicitly for stable references (e.g. 'main_camera').",
    )
    kind: str = Field(description="Device type: 'camera' | 'mount' | 'focuser'")
    adapter_key: str = Field(description="Adapter registered by a plugin, e.g. 'indi_camera'")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Adapter-specific connection parameters (e.g. INDI device name, host, port).",
    )
