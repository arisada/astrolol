"""mDNS plugin — REST API.

GET/PUT /plugins/mdns/settings — what to advertise. Takes effect on next restart,
since the advertisement is registered once at plugin startup (see plugin.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from astrolol.plugins.mdns.models import MdnsSettings

router = APIRouter(prefix="/plugins/mdns", tags=["mdns"])


@router.get("/settings", response_model=MdnsSettings)
async def get_settings(request: Request) -> MdnsSettings:
    raw = request.app.state.profile_store.get_user_settings().plugin_settings.get("mdns", {})
    return MdnsSettings(**raw)


@router.put("/settings", response_model=MdnsSettings)
async def put_settings(body: MdnsSettings, request: Request) -> MdnsSettings:
    store = request.app.state.profile_store
    current = store.get_user_settings()
    updated = {**current.plugin_settings, "mdns": body.model_dump()}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    return body
