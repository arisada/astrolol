"""Hello plugin — REST API.

GET  /hello/property  → { "hello": bool }
POST /hello/property  → body { "hello": bool } → { "hello": bool }
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = structlog.get_logger()


class HelloState(BaseModel):
    hello: bool = False


class HelloProperty(BaseModel):
    hello: bool


router = APIRouter(prefix="/hello", tags=["hello"])


@router.get("/property", response_model=HelloState)
async def get_property(request: Request) -> HelloState:
    return request.app.state.hello_state


@router.post("/property", response_model=HelloState)
async def set_property(request: Request, body: HelloProperty) -> HelloState:
    request.app.state.hello_state = HelloState(hello=body.hello)
    logger.info("hello.property_set", hello=body.hello)
    return request.app.state.hello_state
