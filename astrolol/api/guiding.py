"""Which of the enabled guiding plugins is the one in use."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.core.guiding import (
    GuiderBusy,
    UnknownGuider,
    active_guider_id,
    guiders,
    select_guider,
)
from astrolol.core.guiding.events import ActiveGuiderChanged

router = APIRouter(prefix="/guiding", tags=["guiding"])


class ActiveGuider(BaseModel):
    active: str | None
    available: list[str]


class SelectGuider(BaseModel):
    guider: str


def _current(request: Request) -> ActiveGuider:
    return ActiveGuider(active=active_guider_id(request.app), available=list(guiders(request.app)))


@router.get("/active", response_model=ActiveGuider)
async def get_active_guider(request: Request) -> ActiveGuider:
    """The guiding plugin in use, and the enabled ones that could be."""
    return _current(request)


@router.put("/active", response_model=ActiveGuider)
async def put_active_guider(body: SelectGuider, request: Request) -> ActiveGuider:
    """Use another enabled guiding plugin. Refused (409) while the current one is guiding."""
    try:
        select_guider(request.app, body.guider)
    except UnknownGuider as exc:
        raise HTTPException(status_code=404, detail=f"{body.guider} is not an enabled guiding plugin") from exc
    except GuiderBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store = request.app.state.profile_store
    current = store.get_user_settings()
    store.update_user_settings(current.model_copy(update={"active_guider": body.guider}))
    state = _current(request)
    await request.app.state.event_bus.publish(
        ActiveGuiderChanged(active=state.active, available=state.available)
    )
    return state
