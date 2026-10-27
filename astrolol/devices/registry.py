from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Type

from astrolol.devices.base import ICamera, IMount, IFocuser, IFilterWheel, IRotator, IFlatPanel


@dataclass
class DeviceRegistry:
    cameras: dict[str, Type[ICamera]] = field(default_factory=dict)
    mounts: dict[str, Type[IMount]] = field(default_factory=dict)
    focusers: dict[str, Type[IFocuser]] = field(default_factory=dict)
    filter_wheels: dict[str, Type[IFilterWheel]] = field(default_factory=dict)
    rotators: dict[str, Type[IRotator]] = field(default_factory=dict)
    flat_panels: dict[str, Type[IFlatPanel]] = field(default_factory=dict)
    indi_raws: dict[str, Any] = field(default_factory=dict)
    # Set by the INDI plugin so properties and load-driver endpoints can reach INDI
    indi_client: Any = None
    indi_manager: Any = None
    # Optional async callable: (DeviceConfig) -> list[DeviceConfig]
    # Set by the INDI plugin for multi-role companion discovery.
    companion_discoverer: Any = None
    # adapter key → id of the plugin that registered it (core adapters have none).
    sources: dict[str, str] = field(default_factory=dict)
    _registering_plugin: str | None = None

    @contextmanager
    def registering_for(self, plugin_id: str) -> Iterator[None]:
        """Adapters registered inside this block are recorded as *plugin_id*'s."""
        previous, self._registering_plugin = self._registering_plugin, plugin_id
        try:
            yield
        finally:
            self._registering_plugin = previous

    def _record(self, key: str) -> None:
        if self._registering_plugin is not None:
            self.sources[key] = self._registering_plugin

    def register_camera(self, key: str, adapter: Type[ICamera]) -> None:
        self.cameras[key] = adapter
        self._record(key)

    def register_mount(self, key: str, adapter: Type[IMount]) -> None:
        self.mounts[key] = adapter
        self._record(key)

    def register_focuser(self, key: str, adapter: Type[IFocuser]) -> None:
        self.focusers[key] = adapter
        self._record(key)

    def register_filter_wheel(self, key: str, adapter: Type[IFilterWheel]) -> None:
        self.filter_wheels[key] = adapter
        self._record(key)

    def register_rotator(self, key: str, adapter: Type[IRotator]) -> None:
        self.rotators[key] = adapter
        self._record(key)

    def register_flat_panel(self, key: str, adapter: Type[IFlatPanel]) -> None:
        self.flat_panels[key] = adapter
        self._record(key)

    def register_indi_raw(self, key: str, adapter: Any) -> None:
        self.indi_raws[key] = adapter
        self._record(key)

    def adapters_for_kind(self, kind: str) -> dict[str, Any]:
        return {
            "camera": self.cameras,
            "mount": self.mounts,
            "focuser": self.focusers,
            "filter_wheel": self.filter_wheels,
            "rotator": self.rotators,
            "flat_panel": self.flat_panels,
            "indi": self.indi_raws,
        }.get(kind, {})

    def default_connect_params(self, kind: str, key: str) -> dict[str, Any]:
        """Params an adapter suggests for the connect form (its DEFAULT_CONNECT_PARAMS, if any)."""
        adapter = self.adapters_for_kind(kind).get(key)
        if adapter is None:
            raise KeyError(f"No adapter '{key}' registered for kind '{kind}'")
        return dict(getattr(adapter, "DEFAULT_CONNECT_PARAMS", {}))

    def all_keys(self) -> dict[str, list[str]]:
        return {
            "cameras": list(self.cameras),
            "mounts": list(self.mounts),
            "focusers": list(self.focusers),
            "filter_wheels": list(self.filter_wheels),
            "rotators": list(self.rotators),
            "flat_panels": list(self.flat_panels),
            "indi_raws": list(self.indi_raws),
        }
