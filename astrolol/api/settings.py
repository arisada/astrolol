from fastapi import APIRouter, Request

from astrolol.app import resolve_enabled_plugins, sync_enabled_plugins
from astrolol.config.user_settings import UserSettings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
async def get_settings(request: Request) -> UserSettings:
    return request.app.state.profile_store.get_user_settings()


@router.put("", response_model=UserSettings)
async def put_settings(request: Request, body: UserSettings) -> UserSettings:
    updated = request.app.state.profile_store.update_user_settings(body)

    discovered = request.app.state.discovered_plugins
    target = resolve_enabled_plugins(discovered, body.enabled_plugins)
    await sync_enabled_plugins(request.app, request.app.state.plugin_ctx, discovered, target)

    return updated
