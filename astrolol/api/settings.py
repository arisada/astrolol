from fastapi import APIRouter, HTTPException, Request

from astrolol.app import resolve_enabled_plugins, sync_enabled_plugins
from astrolol.config.settings import OutsideStorage, storage_path
from astrolol.config.user_settings import UserSettings
from astrolol.core.auth import Level, principal_of
from astrolol.imaging.imager import _expand_template

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
async def get_settings(request: Request) -> UserSettings:
    settings = request.app.state.profile_store.get_user_settings()
    principal = principal_of(request)
    if principal is not None and principal.level < Level.ADMIN:
        # Plugin settings can hold credentials (hotspot password, ...): admins only.
        settings = settings.model_copy(update={"plugin_settings": {}})
    return settings


@router.put("", response_model=UserSettings)
async def put_settings(request: Request, body: UserSettings) -> UserSettings:
    store = request.app.state.profile_store
    if body.save_dir_template != store.get_user_settings().save_dir_template:
        # Checked again for every frame saved, with the real values.
        try:
            storage_path(_expand_template(body.save_dir_template, "light", 1, 1.0, None))
        except OutsideStorage as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated = store.update_user_settings(body)

    discovered = request.app.state.discovered_plugins
    target = resolve_enabled_plugins(discovered, body.enabled_plugins)
    await sync_enabled_plugins(request.app, request.app.state.plugin_ctx, discovered, target)

    return updated
