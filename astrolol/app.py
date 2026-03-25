import pluggy
import structlog

from astrolol.plugin import AstrololSpec, PROJECT_NAME
from astrolol.devices.registry import DeviceRegistry

logger = structlog.get_logger()


def build_plugin_manager() -> pluggy.PluginManager:
    pm = pluggy.PluginManager(PROJECT_NAME)
    pm.add_hookspecs(AstrololSpec)

    # Register bundled INDI plugin (gracefully skipped when pyindi-client absent)
    from astrolol.devices.indi.plugin import IndiPlugin
    pm.register(IndiPlugin())

    # Also load any third-party plugins installed via entry points
    pm.load_setuptools_entrypoints(PROJECT_NAME)
    logger.info("plugins.loaded", plugins=[str(p) for p in pm.get_plugins()])
    return pm


def build_registry(pm: pluggy.PluginManager) -> DeviceRegistry:
    registry = DeviceRegistry()
    pm.hook.register_devices(registry=registry)
    logger.info("devices.registered", available=registry.all_keys())
    return registry
