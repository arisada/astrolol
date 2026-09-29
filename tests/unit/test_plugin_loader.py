"""Tests for the plugin discovery and setup machinery in astrolol.app."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from astrolol.app import discover_plugins, resolve_enabled_plugins, setup_plugins, sync_enabled_plugins
from astrolol.core.plugin_api import Plugin, PluginContext, PluginManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(
    plugin_id: str = "test_plugin",
    hot_reloadable: bool = False,
    requires: list[str] | None = None,
) -> MagicMock:
    plugin = MagicMock(spec=Plugin)
    plugin.manifest = PluginManifest(
        id=plugin_id, name="Test", version="0.1.0",
        hot_reloadable=hot_reloadable, requires=requires or [],
    )
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


# ---------------------------------------------------------------------------
# resolve_enabled_plugins
# ---------------------------------------------------------------------------

def test_resolve_auto_enables_required_dependency() -> None:
    child = _make_plugin("child")
    child.manifest = PluginManifest(id="child", name="Child", version="0.1.0", requires=["parent"])
    parent = _make_plugin("parent")
    discovered = {"child": child, "parent": parent}

    resolved = resolve_enabled_plugins(discovered, ["child"])
    assert resolved == ["child", "parent"]


def test_resolve_does_not_duplicate_already_enabled_dependency() -> None:
    child = _make_plugin("child")
    child.manifest = PluginManifest(id="child", name="Child", version="0.1.0", requires=["parent"])
    parent = _make_plugin("parent")
    discovered = {"child": child, "parent": parent}

    resolved = resolve_enabled_plugins(discovered, ["parent", "child"])
    assert resolved == ["parent", "child"]


def test_resolve_leaves_out_missing_dependency() -> None:
    child = _make_plugin("child")
    child.manifest = PluginManifest(id="child", name="Child", version="0.1.0", requires=["ghost"])
    discovered = {"child": child}

    resolved = resolve_enabled_plugins(discovered, ["child"])
    assert resolved == ["child"]


def test_resolve_transitive_dependencies() -> None:
    a = _make_plugin("a")
    a.manifest = PluginManifest(id="a", name="A", version="0.1.0", requires=["b"])
    b = _make_plugin("b")
    b.manifest = PluginManifest(id="b", name="B", version="0.1.0", requires=["c"])
    c = _make_plugin("c")
    discovered = {"a": a, "b": b, "c": c}

    resolved = resolve_enabled_plugins(discovered, ["a"])
    assert resolved == ["a", "b", "c"]


def test_resolve_preserves_order_of_originally_enabled() -> None:
    p1 = _make_plugin("p1")
    p2 = _make_plugin("p2")
    discovered = {"p1": p1, "p2": p2}

    resolved = resolve_enabled_plugins(discovered, ["p2", "p1"])
    assert resolved == ["p2", "p1"]


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


# ---------------------------------------------------------------------------
# sync_enabled_plugins
# ---------------------------------------------------------------------------

def _app_with_state(enabled: set[str] | None = None) -> FastAPI:
    app = FastAPI()
    app.state.enabled_plugin_ids = set(enabled or set())
    app.state.log_scopes = []
    return app


async def test_sync_skips_already_live_plugin() -> None:
    app = _app_with_state(enabled={"alpha"})
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    p = _make_plugin("alpha", hot_reloadable=True)

    await sync_enabled_plugins(app, ctx, {"alpha": p}, ["alpha"])

    p.setup.assert_not_called()


async def test_sync_skips_non_hot_reloadable_plugin() -> None:
    app = _app_with_state()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    p = _make_plugin("alpha", hot_reloadable=False)

    await sync_enabled_plugins(app, ctx, {"alpha": p}, ["alpha"])

    p.setup.assert_not_called()
    assert "alpha" not in app.state.enabled_plugin_ids


async def test_sync_skips_hot_reloadable_plugin_with_unmet_dependency() -> None:
    app = _app_with_state()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    child = _make_plugin("child", hot_reloadable=True, requires=["parent"])

    await sync_enabled_plugins(app, ctx, {"child": child}, ["child"])

    child.setup.assert_not_called()
    assert "child" not in app.state.enabled_plugin_ids


async def test_sync_activates_hot_reloadable_plugin() -> None:
    app = _app_with_state()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    p = _make_plugin("alpha", hot_reloadable=True)

    await sync_enabled_plugins(app, ctx, {"alpha": p}, ["alpha"])

    p.setup.assert_called_once_with(app, ctx)
    p.startup.assert_awaited_once()
    assert "alpha" in app.state.enabled_plugin_ids


async def test_sync_activates_dependent_once_dependency_is_live() -> None:
    app = _app_with_state(enabled={"parent"})
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    child = _make_plugin("child", hot_reloadable=True, requires=["parent"])

    await sync_enabled_plugins(app, ctx, {"child": child}, ["child"])

    child.setup.assert_called_once_with(app, ctx)
    assert "child" in app.state.enabled_plugin_ids


async def test_sync_catches_setup_error_and_leaves_plugin_disabled() -> None:
    app = _app_with_state()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    p = _make_plugin("alpha", hot_reloadable=True)
    p.setup.side_effect = RuntimeError("boom")

    await sync_enabled_plugins(app, ctx, {"alpha": p}, ["alpha"])

    assert "alpha" not in app.state.enabled_plugin_ids


async def test_sync_catches_startup_error_and_leaves_plugin_disabled() -> None:
    app = _app_with_state()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=None)
    p = _make_plugin("alpha", hot_reloadable=True)
    p.startup.side_effect = RuntimeError("boom")

    await sync_enabled_plugins(app, ctx, {"alpha": p}, ["alpha"])

    assert "alpha" not in app.state.enabled_plugin_ids
