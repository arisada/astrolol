import uvicorn
import structlog
from fastapi import FastAPI

from astrolol.app import build_plugin_manager, build_registry

logger = structlog.get_logger()


def create_app() -> FastAPI:
    app = FastAPI(title="astrolol", version="0.1.0")
    pm = build_plugin_manager()
    registry = build_registry(pm)

    # Attach to app state so routes can access them
    app.state.registry = registry
    app.state.plugin_manager = pm

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/devices")
    async def list_devices() -> dict[str, list[str]]:
        return app.state.registry.all_keys()

    return app


def run() -> None:
    uvicorn.run("astrolol.main:create_app", factory=True, host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
