"""Plugin API — the contract between astrolol core and feature plugins.

Every feature plugin must expose a class satisfying the Plugin protocol and a
module-level ``get_plugin()`` factory function.  The core never imports plugin
code directly; it only calls ``get_plugin()`` after discovering the module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from fastapi import FastAPI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LogScope:
    """A named logging scope that can have its verbosity toggled at runtime."""
    key: str      # stable ID matching the component label (e.g. "phd2", "imager")
    label: str    # human-readable name shown in the UI (e.g. "PHD2 Guiding")
    logger: str   # stdlib logger hierarchy root (e.g. "plugins.phd2")


@dataclass
class PluginManifest:
    """Metadata declared by every plugin.  Consumed by the loader and the /plugins API."""
    id: str                              # stable machine identifier, e.g. "imaging"
    name: str                            # human-readable, shown in the Options page
    version: str
    description: str = ""
    requires: list[str] = field(default_factory=list)  # IDs of plugins this one depends on
    nav_order: int = 0                   # sidebar sort key — lower = higher in the list
    log_scopes: list[LogScope] = field(default_factory=list)  # verbosity scopes for this plugin


@dataclass
class PluginContext:
    """Dependency-injection container passed to Plugin.setup().

    Plugins must NOT import from each other directly.  Shared services are
    accessed here, and inter-plugin communication uses the EventBus.
    """
    event_bus: Any         # astrolol.core.events.bus.EventBus
    device_manager: Any    # astrolol.devices.manager.DeviceManager
    device_registry: Any   # astrolol.devices.registry.DeviceRegistry
    profile_store: Any = None  # astrolol.profiles.store.ProfileStore

    def get_plugin_settings(self, plugin_id: str, model: type[T]) -> T:
        """Return plugin settings parsed into *model*, falling back to defaults."""
        if self.profile_store is None:
            return model()
        raw = self.profile_store.get_user_settings().plugin_settings.get(plugin_id, {})
        return model(**raw)

    def save_plugin_settings(self, plugin_id: str, settings: BaseModel) -> None:
        """Persist plugin settings under *plugin_id* in the profile store."""
        if self.profile_store is None:
            return
        current = self.profile_store.get_user_settings()
        new_ps = {**current.plugin_settings, plugin_id: settings.model_dump()}
        self.profile_store.update_user_settings(current.model_copy(update={"plugin_settings": new_ps}))


@runtime_checkable
class Plugin(Protocol):
    """Every feature plugin must satisfy this protocol."""

    manifest: PluginManifest

    def setup(self, app: FastAPI, ctx: PluginContext) -> None:
        """Register routes, create managers, attach state to app.state.

        Called once, synchronously, during app creation.  The app is not yet
        serving requests at this point.
        """
        ...

    async def startup(self) -> None:
        """Called inside the FastAPI lifespan after all plugins are set up."""
        ...

    async def shutdown(self) -> None:
        """Called at lifespan teardown — cancel tasks, release resources."""
        ...
