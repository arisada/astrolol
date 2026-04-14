"""Plugin API — the contract between astrolol core and feature plugins.

Every feature plugin must expose a class satisfying the Plugin protocol and a
module-level ``get_plugin()`` factory function.  The core never imports plugin
code directly; it only calls ``get_plugin()`` after discovering the module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from fastapi import FastAPI


@dataclass
class PluginManifest:
    """Metadata declared by every plugin.  Consumed by the loader and the /plugins API."""
    id: str                              # stable machine identifier, e.g. "imaging"
    name: str                            # human-readable, shown in the Options page
    version: str
    description: str = ""
    requires: list[str] = field(default_factory=list)  # IDs of plugins this one depends on


@dataclass
class PluginContext:
    """Dependency-injection container passed to Plugin.setup().

    Plugins must NOT import from each other directly.  Shared services are
    accessed here, and inter-plugin communication uses the EventBus.
    """
    event_bus: Any         # astrolol.core.events.bus.EventBus
    device_manager: Any    # astrolol.devices.manager.DeviceManager
    device_registry: Any   # astrolol.devices.registry.DeviceRegistry


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
