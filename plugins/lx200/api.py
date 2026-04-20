"""FastAPI router for the LX200 telescope server plugin."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from plugins.lx200.server import Lx200Server

logger = structlog.get_logger()
router = APIRouter(prefix="/lx200", tags=["lx200"])


class Lx200Status(BaseModel):
    running: bool
    port: int
    clients_connected: int


def _server(request: Request) -> Lx200Server:
    return request.app.state.lx200_server


@router.get("/status", response_model=Lx200Status)
async def get_status(request: Request) -> Lx200Status:
    """Return current LX200 server status."""
    srv = _server(request)
    return Lx200Status(
        running=srv.is_running,
        port=srv.port,
        clients_connected=srv.client_count,
    )


@router.post("/start", status_code=204)
async def start_server(request: Request) -> None:
    """Start the LX200 TCP server."""
    try:
        await _server(request).start()
    except Exception as exc:
        logger.warning("lx200.start_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/stop", status_code=204)
async def stop_server(request: Request) -> None:
    """Stop the LX200 TCP server."""
    try:
        await _server(request).stop()
    except Exception as exc:
        logger.warning("lx200.stop_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
