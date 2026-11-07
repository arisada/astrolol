"""The live event stream (``/ws/events``).

Besides the events, the stream carries two control messages so a client can tell that it is no
longer in step: ``ws.heartbeat`` whenever nothing was sent for a while (a phone that slept or a
wifi that changed leaves a socket that looks open and is silent), and ``ws.resync`` when events
were dropped because the client read too slowly. On either problem the client reconnects, which
replays the recent history and refreshes its state.
"""
from __future__ import annotations

import asyncio

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from astrolol.core.events.bus import CLIENT_QUEUE_SIZE, EventBus

logger = structlog.get_logger()

HEARTBEAT_S = 10.0
HEARTBEAT = '{"type":"ws.heartbeat"}'
RESYNC = '{"type":"ws.resync"}'


async def serve_events(websocket: WebSocket, bus: EventBus) -> None:
    await websocket.accept()
    q = bus.subscribe(maxsize=CLIENT_QUEUE_SIZE)
    logger.info("ws.client_connected", subscribers=bus.subscriber_count)
    dropped = 0
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
            except asyncio.TimeoutError:
                await websocket.send_text(HEARTBEAT)
                continue
            if bus.dropped_for(q) != dropped:
                dropped = bus.dropped_for(q)
                await websocket.send_text(RESYNC)
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)
        logger.info("ws.client_disconnected", subscribers=bus.subscriber_count)
