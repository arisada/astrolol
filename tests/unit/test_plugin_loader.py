"""Tests for the plugin discovery and setup machinery in astrolol.app."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from astrolol.app import discover_plugins, setup_plugins
from astrolol.core.plugin_api import Plugin, PluginContext, PluginManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(plugin_id: str = "test_plugin") -> MagicMock:
    plugin = MagicMock(spec=Plugin)
    plugin.manifest = PluginManifest(id=plugin_id, name="Test", version="0.1.0")
    return plugin


def _make_plugin_module(plugin_id: str) -> MagicMock:
    mod = MagicMock(spec=ModuleType)
    mod.get_plugin.return_value = _make_plugin(plugin_id)
    return mod


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------

def test_discover_finds_hello_plugin() -> None:
    """The bundled hello plugin is discovered successfully."""
    discovered = discover_plugins()
    assert "hello" in discovered


def test_discover_hello_manifest() -> None:
    discovered = discover_plugins()
    m = discovered["hello"].manifest
    assert m.id == "hello"
    assert m.name == "Hello World"
    assert m.version == "0.1.0"


def test_discover_empty_when_dir_missing(tmp_path) -> None:
    """Returns empty dict when the plugins directory does not exist."""
    missing = tmp_path / "nonexistent_plugins"
    with patch("astrolol.app.PLUGINS_DIR", missing):
        result = discover_plugins()
    assert result == {}


def test_discover_skips_dirs_without_plugin_py(tmp_path) -> None:
    plugin_dir = tmp_path / "no_plugin_py"
    plugin_dir.mkdir()
    # No plugin.py file — should be silently skipped
    with patch("astrolol.app.PLUGINS_DIR", tmp_path):
        result = discover_plugins()
    assert "no_plugin_py" not in result


def test_discover_skips_underscore_dirs(tmp_path) -> None:
    private_dir = tmp_path / "_internal"
    private_dir.mkdir()
    (private_dir / "plugin.py").write_text("def get_plugin(): raise RuntimeError('should not be called')")
    with patch("astrolol.app.PLUGINS_DIR", tmp_path):
        result = discover_plugins()
    assert "_internal" not in result


def test_discover_skips_files_not_dirs(tmp_path) -> None:
    (tmp_path / "notadir.py").write_text("# file, not dir")
    with patch("astrolol.app.PLUGINS_DIR", tmp_path):
        result = discover_plugins()
    assert not result


def test_discover_logs_warning_on_import_error(tmp_path, caplog) -> None:
    bad_dir = tmp_path / "broken"
    bad_dir.mkdir()
    (bad_dir / "plugin.py").write_text("raise ImportError('oops')")
    with patch("astrolol.app.PLUGINS_DIR", tmp_path):
        result = discover_plugins()
    assert "broken" not in result


# ---------------------------------------------------------------------------
# setup_plugins
# ---------------------------------------------------------------------------

def test_setup_calls_setup_for_enabled() -> None:
    app = FastAPI()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    p = _make_plugin("alpha")
    setup_plugins(app, ctx, {"alpha": p}, ["alpha"])
    p.setup.assert_called_once_with(app, ctx)


def test_setup_skips_disabled() -> None:
    app = FastAPI()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    p = _make_plugin("alpha")
    setup_plugins(app, ctx, {"alpha": p}, [])
    p.setup.assert_not_called()


def test_setup_warns_unknown_plugin_id(caplog) -> None:
    import logging
    app = FastAPI()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    with caplog.at_level(logging.WARNING, logger="astrolol.app"):
        setup_plugins(app, ctx, {}, ["unknown_id"])
    assert "unknown_id" in caplog.text


def test_setup_warns_missing_dependency(caplog) -> None:
    import logging
    app = FastAPI()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    p = _make_plugin("child")
    p.manifest = PluginManifest(id="child", name="Child", version="0.1.0", requires=["parent"])
    with caplog.at_level(logging.WARNING, logger="astrolol.app"):
        setup_plugins(app, ctx, {"child": p}, ["child"])
    assert "parent" in caplog.text


def test_setup_continues_after_plugin_setup_error() -> None:
    """A plugin that raises in setup() should not prevent other plugins from loading."""
    app = FastAPI()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)

    bad = _make_plugin("bad")
    bad.setup.side_effect = RuntimeError("boom")

    good = _make_plugin("good")

    setup_plugins(app, ctx, {"bad": bad, "good": good}, ["bad", "good"])
    good.setup.assert_called_once_with(app, ctx)


def test_setup_order_matches_enabled_list() -> None:
    app = FastAPI()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    calls = []

    for pid in ("alpha", "beta", "gamma"):
        p = _make_plugin(pid)
        p.setup.side_effect = lambda _app, _ctx, _id=pid: calls.append(_id)

    discovered = {pid: _make_plugin(pid) for pid in ("alpha", "beta", "gamma")}
    for pid, p in discovered.items():
        p.setup.side_effect = lambda _app, _ctx, _id=pid: calls.append(_id)

    setup_plugins(app, ctx, discovered, ["gamma", "alpha", "beta"])
    assert calls == ["gamma", "alpha", "beta"]
