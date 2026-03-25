import uvicorn
import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from astrolol.app import build_plugin_manager, build_registry
from astrolol.core.events import EventBus

logger = structlog.get_logger()


def create_app() -> FastAPI:
    app = FastAPI(title="astrolol", version="0.1.0")
    pm = build_plugin_manager()
    registry = build_registry(pm)
    event_bus = EventBus()

    app.state.registry = registry
    app.state.plugin_manager = pm
    app.state.event_bus = event_bus

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/devices")
    async def list_devices() -> dict[str, list[str]]:
        return app.state.registry.all_keys()

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
