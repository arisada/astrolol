"""Application bootstrap: device adapters (pluggy) and feature plugins."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Optional

import pluggy
import structlog

from astrolol.core.plugin_api import Plugin, PluginContext
from astrolol.plugin import AstrololSpec, PROJECT_NAME
from astrolol.devices.registry import DeviceRegistry

logger = structlog.get_logger()

# Feature plugins live next to the astrolol package, one sub-directory each.
PLUGINS_DIR = Path(__file__).parent.parent / "plugins"


# ── Device-adapter plugin system (pluggy) ────────────────────────────────────

def build_plugin_manager() -> pluggy.PluginManager:
    pm = pluggy.PluginManager(PROJECT_NAME)
    pm.add_hookspecs(AstrololSpec)

    # Register bundled INDI plugin (gracefully skipped when indipyclient absent)
    from astrolol.devices.indi.plugin import IndiPlugin
    pm.register(IndiPlugin())

    # Also load any third-party device plugins installed via entry points
    pm.load_setuptools_entrypoints(PROJECT_NAME)
    logger.info("plugins.loaded", plugins=[str(p) for p in pm.get_plugins()])
    return pm


def build_registry(pm: pluggy.PluginManager, indi_run_dir: Optional[Path] = None) -> DeviceRegistry:
    registry = DeviceRegistry()
    registry.indi_run_dir = indi_run_dir or Path("/tmp/astrolol")
    pm.hook.register_devices(registry=registry)
    logger.info("devices.registered", available=registry.all_keys())
    return registry


# ── Feature plugin system ─────────────────────────────────────────────────────

def discover_plugins() -> dict[str, Plugin]:
    """Scan ``plugins/`` and return a mapping of plugin-id → Plugin instance.

    Every sub-directory with a ``plugin.py`` that exports ``get_plugin()`` is
    considered a plugin.  Directories whose names start with ``_`` are ignored.
    Import errors are logged and the offending plugin is skipped.
    """
    discovered: dict[str, Plugin] = {}

    if not PLUGINS_DIR.exists():
        logger.debug("plugins.dir_not_found", path=str(PLUGINS_DIR))
        return discovered

    for item in sorted(PLUGINS_DIR.iterdir()):
        if not item.is_dir() or item.name.startswith("_"):
            continue
        if not (item / "plugin.py").exists():
            continue
        module_path = f"plugins.{item.name}.plugin"
        try:
            mod = importlib.import_module(module_path)
            instance: Plugin = mod.get_plugin()
            discovered[instance.manifest.id] = instance
            logger.debug("plugin.discovered", plugin_id=instance.manifest.id)
        except Exception as exc:
            logger.warning("plugin.discover_failed", directory=item.name, error=str(exc))

    return discovered


def resolve_enabled_plugins(discovered: dict[str, Plugin], enabled: list[str]) -> list[str]:
    """Expand *enabled* to include the transitive closure of each plugin's ``requires``.

    A plugin that declares ``requires=["object_resolver"]`` gets that dependency
    auto-enabled alongside it, even if the user never explicitly enabled it.
    Preserves the original order and appends newly auto-enabled dependencies
    right after the plugin that pulled them in. A required plugin that isn't
    among *discovered* is left out here — ``setup_plugins`` still warns about it.
    """
    resolved: list[str] = []
    seen: set[str] = set()

    def _add(plugin_id: str) -> None:
        if plugin_id in seen:
            return
        seen.add(plugin_id)
        resolved.append(plugin_id)
        plugin = discovered.get(plugin_id)
        if plugin is None:
            return
        for req in plugin.manifest.requires:
            if req in discovered and req not in seen:
                logger.info("plugin.auto_enabled", plugin_id=req, required_by=plugin_id)
                _add(req)

    for plugin_id in enabled:
        _add(plugin_id)

    return resolved


def setup_plugins(
    app: "FastAPI",  # type: ignore[name-defined]  # avoid circular at module level
    ctx: PluginContext,
    discovered: dict[str, Plugin],
    enabled: list[str],
) -> None:
    """Call ``plugin.setup()`` for each enabled plugin, in the listed order.

    Unknown plugin IDs are warned and skipped.  Missing dependencies are warned
    but setup still proceeds — the plugin itself will fail gracefully if needed.
    """
    for plugin_id in enabled:
        plugin = discovered.get(plugin_id)
        if plugin is None:
            logger.warning("plugin.not_found", plugin_id=plugin_id)
            continue

        for req in plugin.manifest.requires:
            if req not in enabled:
                logger.warning(
                    "plugin.missing_dependency",
                    plugin_id=plugin_id,
                    requires=req,
                )

        try:
            plugin.setup(app, ctx)
            logger.info("plugin.setup_ok", plugin_id=plugin_id, name=plugin.manifest.name)
        except Exception as exc:
            logger.error("plugin.setup_failed", plugin_id=plugin_id, error=str(exc), exc_info=True)


async def sync_enabled_plugins(
    app: "FastAPI",  # type: ignore[name-defined]
    ctx: PluginContext,
    discovered: dict[str, Plugin],
    target_enabled: list[str],
) -> None:
    """Live-activate any newly-requested plugin that is ``hot_reloadable``.

    Called after ``enabled_plugins`` is persisted (see ``PUT /settings``) to
    reconcile the live app with the user's new intent, without a restart.
    Never disables or tears down a plugin that's already live — disabling
    always requires a restart (FastAPI has no clean route-removal path, and
    most plugins have no real teardown). A plugin that isn't hot_reloadable,
    or whose ``requires`` aren't already live, is left alone: the persisted
    settings still record the user's intent, and ``GET /plugins`` reports it
    as ``pending_restart`` until the next full restart picks it up via the
    normal ``setup_plugins()`` boot path.
    """
    resolved = resolve_enabled_plugins(discovered, target_enabled)
    for plugin_id in resolved:
        if plugin_id in app.state.enabled_plugin_ids:
            continue
        plugin = discovered.get(plugin_id)
        if plugin is None or not plugin.manifest.hot_reloadable:
            continue
        if not all(req in app.state.enabled_plugin_ids for req in plugin.manifest.requires):
            continue
        try:
            plugin.setup(app, ctx)
            await plugin.startup()
        except Exception as exc:
            logger.error("plugin.hot_enable_failed", plugin_id=plugin_id, error=str(exc), exc_info=True)
            continue
        app.state.enabled_plugin_ids.add(plugin_id)
        app.state.log_scopes = app.state.log_scopes + list(plugin.manifest.log_scopes)
        logger.info("plugin.hot_enabled", plugin_id=plugin_id, name=plugin.manifest.name)
