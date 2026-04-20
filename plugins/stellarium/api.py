"""FastAPI router for the Stellarium telescope server plugin."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from plugins.stellarium.server import StellariumServer

logger = structlog.get_logger()
router = APIRouter(prefix="/stellarium", tags=["stellarium"])


class StellariumStatus(BaseModel):
    running: bool
    port: int
    clients_connected: int


def _server(request: Request) -> StellariumServer:
    return request.app.state.stellarium_server


@router.get("/status", response_model=StellariumStatus)
async def get_status(request: Request) -> StellariumStatus:
    srv = _server(request)
    return StellariumStatus(
        running=srv.is_running,
        port=srv.port,
        clients_connected=srv.client_count,
    )


@router.post("/start", status_code=204)
async def start_server(request: Request) -> None:
    try:
        await _server(request).start()
    except Exception as exc:
        logger.warning("stellarium.start_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/stop", status_code=204)
async def stop_server(request: Request) -> None:
    try:
        await _server(request).stop()
    except Exception as exc:
        logger.warning("stellarium.stop_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
