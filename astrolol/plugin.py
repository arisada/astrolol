import pluggy

PROJECT_NAME = "astrolol"

hookspec = pluggy.HookspecMarker(PROJECT_NAME)
hookimpl = pluggy.HookimplMarker(PROJECT_NAME)


class AstrololSpec:
    @hookspec
    def register_devices(self, registry: "DeviceRegistry") -> None:
        """Called at startup. Plugins register their device adapter classes."""
