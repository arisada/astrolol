from dataclasses import dataclass, field
from typing import Type

from astrolol.devices.base import ICamera, IMount, IFocuser


@dataclass
class DeviceRegistry:
    cameras: dict[str, Type[ICamera]] = field(default_factory=dict)
    mounts: dict[str, Type[IMount]] = field(default_factory=dict)
    focusers: dict[str, Type[IFocuser]] = field(default_factory=dict)

    def register_camera(self, key: str, adapter: Type[ICamera]) -> None:
        self.cameras[key] = adapter

    def register_mount(self, key: str, adapter: Type[IMount]) -> None:
        self.mounts[key] = adapter

    def register_focuser(self, key: str, adapter: Type[IFocuser]) -> None:
        self.focusers[key] = adapter

    def all_keys(self) -> dict[str, list[str]]:
        return {
            "cameras": list(self.cameras),
            "mounts": list(self.mounts),
            "focusers": list(self.focusers),
        }
