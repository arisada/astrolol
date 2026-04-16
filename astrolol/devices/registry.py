from dataclasses import dataclass, field
from typing import Any, Type

from astrolol.devices.base import ICamera, IMount, IFocuser, IFilterWheel, IRotator


@dataclass
class DeviceRegistry:
    cameras: dict[str, Type[ICamera]] = field(default_factory=dict)
    mounts: dict[str, Type[IMount]] = field(default_factory=dict)
    focusers: dict[str, Type[IFocuser]] = field(default_factory=dict)
    filter_wheels: dict[str, Type[IFilterWheel]] = field(default_factory=dict)
    rotators: dict[str, Type[IRotator]] = field(default_factory=dict)
    indi_raws: dict[str, Any] = field(default_factory=dict)
    # Set by the INDI plugin so properties and load-driver endpoints can reach INDI
    indi_client: Any = None
    indi_manager: Any = None
    # Optional async callable: (DeviceConfig) -> list[DeviceConfig]
    # Set by the INDI plugin for multi-role companion discovery.
    companion_discoverer: Any = None

    def register_camera(self, key: str, adapter: Type[ICamera]) -> None:
        self.cameras[key] = adapter

    def register_mount(self, key: str, adapter: Type[IMount]) -> None:
        self.mounts[key] = adapter

    def register_focuser(self, key: str, adapter: Type[IFocuser]) -> None:
        self.focusers[key] = adapter

    def register_filter_wheel(self, key: str, adapter: Type[IFilterWheel]) -> None:
        self.filter_wheels[key] = adapter

    def register_rotator(self, key: str, adapter: Type[IRotator]) -> None:
        self.rotators[key] = adapter

    def register_indi_raw(self, key: str, adapter: Any) -> None:
        self.indi_raws[key] = adapter

    def all_keys(self) -> dict[str, list[str]]:
        return {
            "cameras": list(self.cameras),
            "mounts": list(self.mounts),
            "focusers": list(self.focusers),
            "filter_wheels": list(self.filter_wheels),
            "rotators": list(self.rotators),
            "indi_raws": list(self.indi_raws),
        }
