import traceback
from contextlib import asynccontextmanager

import uvicorn
import structlog
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exception_handlers import http_exception_handler as _default_http_exc_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from astrolol.api.static import mount_ui
from astrolol.api.devices import router as devices_router
from astrolol.api.focuser import router as focuser_router
from astrolol.api.imager import router as imager_router
from astrolol.api.indi import router as indi_router
from astrolol.api.mount import router as mount_router
from astrolol.api.profiles import router as profiles_router
from astrolol.api.properties import router as properties_router
from astrolol.profiles.store import ProfileStore
from astrolol.app import build_plugin_manager, build_registry
from astrolol.core.events import EventBus
from astrolol.devices.manager import DeviceManager
from astrolol.focuser import FocuserManager
from astrolol.imaging import ImagerManager
from astrolol.mount import MountManager

logger = structlog.get_logger()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        # --- Startup ---
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
                    except Exception as exc:
                        logger.warning(
                            "startup.device_connect_failed",
                            device_id=pd.config.device_id,
                            error=str(exc),
                        )
            except KeyError:
                logger.warning("startup.last_profile_not_found", profile_id=last_id)
        yield
        # --- Shutdown (nothing needed yet) ---

    app = FastAPI(title="astrolol", version="0.1.0", lifespan=lifespan)

    pm = build_plugin_manager()
    registry = build_registry(pm)
    event_bus = EventBus()
    device_manager = DeviceManager(registry=registry, event_bus=event_bus)
    imager_manager = ImagerManager(device_manager=device_manager, event_bus=event_bus)
    mount_manager = MountManager(device_manager=device_manager, event_bus=event_bus)
    focuser_manager = FocuserManager(device_manager=device_manager, event_bus=event_bus)

    from astrolol.config.settings import settings as _settings

    app.state.registry = registry
    app.state.plugin_manager = pm
    app.state.event_bus = event_bus
    app.state.device_manager = device_manager
    app.state.imager_manager = imager_manager
    app.state.mount_manager = mount_manager
    app.state.focuser_manager = focuser_manager
    app.state.profile_store = ProfileStore(_settings.profiles_file)
    app.state.active_profile = None

    app.include_router(devices_router)
    app.include_router(properties_router)
    app.include_router(profiles_router)
    app.include_router(imager_router)
    app.include_router(mount_router)
    app.include_router(focuser_router)
    app.include_router(indi_router)

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
