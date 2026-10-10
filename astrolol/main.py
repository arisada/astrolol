import asyncio
import contextlib
import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import structlog

from astrolol.config.settings import settings as _boot_settings
from astrolol.config.logging_setup import setup_logging, event_bus_forwarder

# Configure logging as early as possible so every module sees the right setup
setup_logging(_boot_settings.log_file)
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.exception_handlers import http_exception_handler as _default_http_exc_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from astrolol.api.static import mount_ui
from astrolol.api.bluetooth import router as bluetooth_router
from astrolol.api.devices import router as devices_router
from astrolol.api.filter_wheel import router as filter_wheel_router
from astrolol.api.focuser import router as focuser_router
from astrolol.api.imager import router as imager_router
from astrolol.api.indi import router as indi_router
from astrolol.api.inventory import router as inventory_router
from astrolol.api.mount import router as mount_router
from astrolol.api.profiles import find_profile_site, restore_last_profile, router as profiles_router
from astrolol.api.properties import router as properties_router
from astrolol.api.settings import router as settings_router
from astrolol.equipment.store import EquipmentStore
from astrolol.profiles.store import ProfileStore
from astrolol.app import (
    build_plugin_manager,
    build_registry,
    discover_plugins,
    resolve_enabled_plugins,
    setup_plugins,
)
from astrolol.core.events import EventBus
from astrolol.core.plugin_api import LogScope, PluginContext
from astrolol.devices.bluetooth.backend import BlueZBackend
from astrolol.devices.bluetooth.manager import BluetoothManager
from astrolol.devices.bluetooth.store import BluetoothDeviceStore
from astrolol.devices.manager import DeviceManager
from astrolol.filter_wheel import FilterWheelManager
from astrolol.focuser import FocuserManager
from astrolol.imaging import ImagerManager
from astrolol.mount import MountManager
from astrolol.version import PROTOCOL_VERSION, SERVER_VERSION

logger = structlog.get_logger()

# Core module log scopes (always present regardless of enabled plugins)
_CORE_SCOPES: list[LogScope] = [
    LogScope(key="indi",    label="INDI",    logger="astrolol.devices.indi"),
    LogScope(key="device",  label="Devices", logger="astrolol.devices"),
    LogScope(key="mount",   label="Mount",   logger="astrolol.mount"),
    LogScope(key="imager",  label="Imaging", logger="astrolol.imaging"),
    LogScope(key="focuser", label="Focuser", logger="astrolol.focuser"),
]


async def _restore_profile(app: FastAPI) -> None:
    try:
        await restore_last_profile(app.state)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("startup.profile_restore_failed", error=str(exc), exc_info=True)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        # --- Startup ---

        if os.getenv("PYTHONASYNCIODEBUG"):
            asyncio.get_event_loop().set_debug(True)
            logger.info("asyncio.debug_mode_enabled")

        # Start enabled feature plugins (PHD2, etc.)
        for plugin_id in app.state.enabled_plugin_ids:
            plugin = app.state.discovered_plugins.get(plugin_id)
            if plugin is not None:
                try:
                    await plugin.startup()
                except Exception as exc:
                    logger.error("plugin.startup_failed", plugin_id=plugin_id, error=str(exc), exc_info=True)

        # Restore in the background so the API and UI are up while devices connect
        # (a restart can then be watched from the UI).
        app.state.profile_restore_task = asyncio.create_task(_restore_profile(app))
        yield

        # --- Shutdown ---
        restore_task: asyncio.Task[None] = app.state.profile_restore_task
        if not restore_task.done():
            restore_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await restore_task
        for plugin_id in app.state.enabled_plugin_ids:
            plugin = app.state.discovered_plugins.get(plugin_id)
            if plugin is not None:
                try:
                    await plugin.shutdown()
                except Exception as exc:
                    logger.error("plugin.shutdown_failed", plugin_id=plugin_id, error=str(exc), exc_info=True)

    app = FastAPI(title="astrolol", version=SERVER_VERSION, lifespan=lifespan)

    from astrolol.config.settings import settings as _settings

    profile_store = ProfileStore(_settings.profiles_file)
    equipment_store = EquipmentStore(_settings.inventory_file)
    user_settings = profile_store.get_user_settings()

    # Wire up the global memory-pressure guard so it reads the live setting.
    from astrolol.core import mem_guard as _mem_guard_mod
    _mem_guard_mod.configure(lambda: profile_store.get_user_settings().low_memory_mode)

    pm = build_plugin_manager()
    registry = build_registry(pm, indi_run_dir=Path(user_settings.indi_run_dir))
    event_bus = EventBus()
    event_bus_forwarder.set_bus(event_bus)  # bridge structlog → EventBus
    device_manager = DeviceManager(registry=registry, event_bus=event_bus)

    def _active_site():
        profile = app.state.active_profile
        return find_profile_site(profile, equipment_store) if profile is not None else None

    mount_manager = MountManager(
        device_manager=device_manager, event_bus=event_bus, profile_store=profile_store,
        site_provider=_active_site,
    )
    imager_manager = ImagerManager(device_manager=device_manager, event_bus=event_bus, profile_store=profile_store, equipment_store=equipment_store, mount_manager=mount_manager)
    focuser_manager = FocuserManager(device_manager=device_manager, event_bus=event_bus)
    filter_wheel_manager = FilterWheelManager(device_manager=device_manager, event_bus=event_bus)
    bluetooth_manager = BluetoothManager(
        backend=BlueZBackend(), store=BluetoothDeviceStore(_settings.bluetooth_devices_file)
    )

    app.state.registry = registry
    app.state.plugin_manager = pm
    app.state.event_bus = event_bus
    app.state.device_manager = device_manager
    app.state.bluetooth_manager = bluetooth_manager
    app.state.imager_manager = imager_manager
    app.state.mount_manager = mount_manager
    app.state.focuser_manager = focuser_manager
    app.state.filter_wheel_manager = filter_wheel_manager
    app.state.profile_store = profile_store
    app.state.equipment_store = equipment_store
    app.state.active_profile = None

    # Feature plugins — discover all, set up enabled ones
    # app.state must be fully populated before setup() is called so plugins can
    # access managers and the profile store during their setup phase.
    plugin_ctx = PluginContext(
        event_bus=event_bus,
        device_manager=device_manager,
        device_registry=registry,
        profile_store=profile_store,
        equipment_store=equipment_store,
        bluetooth_manager=bluetooth_manager,
    )
    discovered_plugins = discover_plugins()
    # Auto-enable each enabled plugin's declared dependencies (e.g. "target"
    # requires "object_resolver") without persisting that back to user settings —
    # disabling "target" later naturally drops the dependency too.
    resolved_enabled = resolve_enabled_plugins(discovered_plugins, user_settings.enabled_plugins)
    setup_plugins(app, plugin_ctx, discovered_plugins, resolved_enabled)

    app.state.discovered_plugins = discovered_plugins
    app.state.enabled_plugin_ids = set(resolved_enabled)
    app.state.plugin_ctx = plugin_ctx

    # Collect log scopes: core always present, plus scopes declared by enabled plugins
    plugin_scopes = [
        scope
        for plugin_id in resolved_enabled
        if (plugin := discovered_plugins.get(plugin_id)) is not None
        for scope in plugin.manifest.log_scopes
    ]
    app.state.log_scopes = _CORE_SCOPES + plugin_scopes

    app.include_router(devices_router)
    app.include_router(bluetooth_router)
    app.include_router(properties_router)
    app.include_router(profiles_router)
    app.include_router(inventory_router)
    app.include_router(imager_router)
    app.include_router(mount_router)
    app.include_router(focuser_router)
    app.include_router(filter_wheel_router)
    app.include_router(indi_router)
    app.include_router(settings_router)

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        if exc.status_code >= 500:
            cause = exc.__cause__
            logger.error(
                "api.error",
                method=request.method,
                path=request.url.path,
                status=exc.status_code,
                detail=exc.detail,
                cause=traceback.format_exception(type(cause), cause, cause.__traceback__)
                if cause is not None
                else None,
            )
        return await _default_http_exc_handler(request, exc)

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception):
        logger.exception(
            "api.unhandled_exception",
            method=request.method,
            path=request.url.path,
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    class HealthResponse(BaseModel):
        status: str
        protocol_version: int
        server_version: str
        enabled_plugins: list[str]

    @app.get("/health")
    async def health(request: Request) -> HealthResponse:
        return HealthResponse(
            status="ok",
            protocol_version=PROTOCOL_VERSION,
            server_version=SERVER_VERSION,
            enabled_plugins=sorted(request.app.state.enabled_plugin_ids),
        )

    @app.post("/admin/restart", status_code=202)
    async def admin_restart() -> dict[str, str]:
        """Replace the running process with a fresh instance (same argv/env)."""
        import asyncio
        import os
        import sys

        async def _do_restart() -> None:
            await asyncio.sleep(0.2)  # let the 202 response flush
            logger.info("admin.restart")
            os.execv(sys.executable, [sys.executable] + sys.argv)

        asyncio.create_task(_do_restart())
        return {"status": "restarting"}

    @app.post("/admin/indi/stop", status_code=202)
    async def admin_indi_stop(request: Request) -> dict[str, str]:
        """Explicitly stop the managed indiserver."""
        manager = getattr(request.app.state.registry, "indi_manager", None)
        if manager is None:
            raise HTTPException(status_code=404, detail="INDI is not configured in managed mode")
        await manager.stop_server()
        return {"status": "stopped"}

    class _LogLevelRequest(BaseModel):
        key: str
        level: str  # "debug" | "info"

    @app.get("/admin/log_scopes")
    async def admin_log_scopes(request: Request) -> list[dict]:
        """Return all registered log scopes with their current verbosity level."""
        import logging as _logging
        result = []
        for scope in request.app.state.log_scopes:
            effective = _logging.getLogger(scope.logger).getEffectiveLevel()
            result.append({
                "key": scope.key,
                "label": scope.label,
                "logger": scope.logger,
                "level": "debug" if effective <= _logging.DEBUG else "info",
            })
        return result

    @app.post("/admin/log_level", status_code=204)
    async def admin_log_level(body: _LogLevelRequest, request: Request) -> None:
        """Set the verbosity level for a registered log scope."""
        import logging as _logging
        scopes: list[LogScope] = request.app.state.log_scopes
        scope = next((s for s in scopes if s.key == body.key), None)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"Unknown log scope: {body.key!r}")
        new_level = _logging.DEBUG if body.level == "debug" else _logging.INFO
        _logging.getLogger(scope.logger).setLevel(new_level)
        logger.info("admin.log_level_changed", scope=body.key, level=body.level)

    @app.get("/plugins")
    async def list_plugins(request: Request) -> list[dict]:
        """Return all discovered plugins with their enabled state."""
        discovered: dict = request.app.state.discovered_plugins
        enabled: set = request.app.state.enabled_plugin_ids
        persisted = request.app.state.profile_store.get_user_settings().enabled_plugins
        desired = set(resolve_enabled_plugins(discovered, persisted))
        return [
            {
                "id": p.manifest.id,
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "enabled": p.manifest.id in enabled,
                "nav_order": p.manifest.nav_order,
                "nav_before": p.manifest.nav_before,
                "nav_group": p.manifest.nav_group,
                "hot_reloadable": p.manifest.hot_reloadable,
                # True whenever the persisted desired state (from user settings)
                # disagrees with what's actually live — covers both a newly
                # enabled plugin that couldn't be hot-loaded and a disabled
                # plugin that's still running until the next restart.
                "pending_restart": (p.manifest.id in desired) != (p.manifest.id in enabled),
            }
            for p in discovered.values()
        ]

    @app.get("/plugins/{plugin_id}/settings")
    async def get_plugin_settings(plugin_id: str, request: Request) -> dict:
        """Return persisted settings for a specific plugin (empty dict if none saved)."""
        store: ProfileStore = request.app.state.profile_store
        return store.get_user_settings().plugin_settings.get(plugin_id, {})

    @app.put("/plugins/{plugin_id}/settings")
    async def update_plugin_settings(plugin_id: str, body: dict, request: Request) -> dict:
        """Persist settings for a specific plugin."""
        store: ProfileStore = request.app.state.profile_store
        current = store.get_user_settings()
        new_ps = {**current.plugin_settings, plugin_id: body}
        store.update_user_settings(current.model_copy(update={"plugin_settings": new_ps}))
        return new_ps[plugin_id]

    @app.get("/events/history")
    async def events_history(request: Request) -> list[dict]:
        """Return the ring buffer of recent events for reconnecting clients."""
        bus: EventBus = request.app.state.event_bus
        return [e.model_dump(mode="json") for e in bus.get_history()]

    # Serve built UI — must be last so API routes take priority
    mount_ui(app)

    @app.websocket("/ws/events")
    async def events_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        q = event_bus.subscribe()
        logger.info("ws.client_connected", subscribers=event_bus.subscriber_count)
        try:
            while True:
                event = await q.get()
                await websocket.send_text(event.model_dump_json())
        except WebSocketDisconnect:
            pass
        finally:
            event_bus.unsubscribe(q)
            logger.info("ws.client_disconnected", subscribers=event_bus.subscriber_count)

    return app


def run() -> None:
    uvicorn.run("astrolol.main:create_app", factory=True, host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
