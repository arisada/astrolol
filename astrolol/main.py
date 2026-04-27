import asyncio
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
from fastapi.exception_handlers import http_exception_handler as _default_http_exc_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from astrolol.api.static import mount_ui
from astrolol.api.devices import router as devices_router
from astrolol.api.filter_wheel import router as filter_wheel_router
from astrolol.api.focuser import router as focuser_router
from astrolol.api.imager import router as imager_router
from astrolol.api.indi import router as indi_router
from astrolol.api.mount import router as mount_router
from astrolol.api.profiles import router as profiles_router
from astrolol.api.properties import router as properties_router
from astrolol.api.settings import router as settings_router
from astrolol.profiles.store import ProfileStore
from astrolol.app import build_plugin_manager, build_registry, discover_plugins, setup_plugins
from astrolol.core.events import EventBus
from astrolol.core.plugin_api import PluginContext
from astrolol.devices.manager import DeviceManager
from astrolol.filter_wheel import FilterWheelManager
from astrolol.focuser import FocuserManager
from astrolol.imaging import ImagerManager
from astrolol.mount import MountManager

logger = structlog.get_logger()


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

        store: ProfileStore = app.state.profile_store
        last_id = store.get_last_active_id()
        if last_id is not None:
            try:
                profile = store.get(last_id)
                app.state.active_profile = profile
                app.state.imager_manager.set_context(profile)
                for pd in profile.devices:
                    try:
                        await app.state.device_manager.connect(pd.config)
                        if pd.config.kind == "mount":
                            await app.state.mount_manager.push_site_data(
                                pd.config.device_id, profile.location
                            )
                            app.state.mount_manager.start_automation(pd.config.device_id)
                    except Exception as exc:
                        logger.warning(
                            "startup.device_connect_failed",
                            device_id=pd.config.device_id,
                            error=str(exc),
                        )
                    else:
                        if pd.config.kind == "camera":
                            await app.state.imager_manager.push_scope_info(pd.config.device_id)
            except KeyError:
                logger.warning("startup.last_profile_not_found", profile_id=last_id)
        yield

        # --- Shutdown ---
        for plugin_id in app.state.enabled_plugin_ids:
            plugin = app.state.discovered_plugins.get(plugin_id)
            if plugin is not None:
                try:
                    await plugin.shutdown()
                except Exception as exc:
                    logger.error("plugin.shutdown_failed", plugin_id=plugin_id, error=str(exc), exc_info=True)

    app = FastAPI(title="astrolol", version="0.1.0", lifespan=lifespan)

    from astrolol.config.settings import settings as _settings

    profile_store = ProfileStore(_settings.profiles_file)
    user_settings = profile_store.get_user_settings()

    # Wire up the global memory-pressure guard so it reads the live setting.
    from astrolol.core import mem_guard as _mem_guard_mod
    _mem_guard_mod.configure(lambda: profile_store.get_user_settings().low_memory_mode)

    pm = build_plugin_manager()
    registry = build_registry(pm, indi_run_dir=Path(user_settings.indi_run_dir))
    event_bus = EventBus()
    event_bus_forwarder.set_bus(event_bus)  # bridge structlog → EventBus
    device_manager = DeviceManager(registry=registry, event_bus=event_bus)
    imager_manager = ImagerManager(device_manager=device_manager, event_bus=event_bus, profile_store=profile_store)
    mount_manager = MountManager(device_manager=device_manager, event_bus=event_bus, profile_store=profile_store)
    focuser_manager = FocuserManager(device_manager=device_manager, event_bus=event_bus)
    filter_wheel_manager = FilterWheelManager(device_manager=device_manager, event_bus=event_bus)

    app.state.registry = registry
    app.state.plugin_manager = pm
    app.state.event_bus = event_bus
    app.state.device_manager = device_manager
    app.state.imager_manager = imager_manager
    app.state.mount_manager = mount_manager
    app.state.focuser_manager = focuser_manager
    app.state.filter_wheel_manager = filter_wheel_manager
    app.state.profile_store = profile_store
    app.state.active_profile = None

    # Feature plugins — discover all, set up enabled ones
    # app.state must be fully populated before setup() is called so plugins can
    # access managers and the profile store during their setup phase.
    plugin_ctx = PluginContext(
        event_bus=event_bus,
        device_manager=device_manager,
        device_registry=registry,
        profile_store=profile_store,
    )
    discovered_plugins = discover_plugins()
    setup_plugins(app, plugin_ctx, discovered_plugins, user_settings.enabled_plugins)

    app.state.discovered_plugins = discovered_plugins
    app.state.enabled_plugin_ids = set(user_settings.enabled_plugins)

    app.include_router(devices_router)
    app.include_router(properties_router)
    app.include_router(profiles_router)
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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

    @app.get("/plugins")
    async def list_plugins(request: Request) -> list[dict]:
        """Return all discovered plugins with their enabled state."""
        discovered: dict = request.app.state.discovered_plugins
        enabled: set = request.app.state.enabled_plugin_ids
        return [
            {
                "id": p.manifest.id,
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "enabled": p.manifest.id in enabled,
                "nav_order": p.manifest.nav_order,
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
