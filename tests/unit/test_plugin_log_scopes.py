"""Plugin log scopes must name loggers that really exist under astrolol.plugins."""
import importlib

from astrolol.app import PLUGINS_DIR, discover_plugins


def test_scope_loggers_point_at_the_plugin_package():
    # A stale logger name makes the Logs-page verbosity toggle silently do nothing.
    dirs = {p.name for p in PLUGINS_DIR.iterdir() if (p / "plugin.py").exists() and not p.name.startswith("_")}
    for plugin in discover_plugins().values():
        for scope in plugin.manifest.log_scopes:
            assert scope.logger.startswith("astrolol.plugins."), scope
            package = scope.logger.split(".")[2]
            assert package in dirs, scope
            importlib.import_module(f"astrolol.plugins.{package}")
