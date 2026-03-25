import uvicorn
import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from astrolol.api.static import mount_ui
from astrolol.api.devices import router as devices_router
from astrolol.api.focuser import router as focuser_router
from astrolol.api.imager import router as imager_router
from astrolol.api.indi import router as indi_router
from astrolol.api.mount import router as mount_router
from astrolol.app import build_plugin_manager, build_registry
from astrolol.core.events import EventBus
from astrolol.devices.manager import DeviceManager
from astrolol.focuser import FocuserManager
from astrolol.imaging import ImagerManager
from astrolol.mount import MountManager

logger = structlog.get_logger()


def create_app() -> FastAPI:
    app = FastAPI(title="astrolol", version="0.1.0")

    pm = build_plugin_manager()
    registry = build_registry(pm)
    event_bus = EventBus()
    device_manager = DeviceManager(registry=registry, event_bus=event_bus)
    imager_manager = ImagerManager(device_manager=device_manager, event_bus=event_bus)
    mount_manager = MountManager(device_manager=device_manager, event_bus=event_bus)
    focuser_manager = FocuserManager(device_manager=device_manager, event_bus=event_bus)

    app.state.registry = registry
    app.state.plugin_manager = pm
    app.state.event_bus = event_bus
    app.state.device_manager = device_manager
    app.state.imager_manager = imager_manager
    app.state.mount_manager = mount_manager
    app.state.focuser_manager = focuser_manager

    app.include_router(devices_router)
    app.include_router(imager_router)
    app.include_router(mount_router)
    app.include_router(focuser_router)
    app.include_router(indi_router)

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
