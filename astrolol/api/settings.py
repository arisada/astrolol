from fastapi import APIRouter, Request

from astrolol.config.user_settings import UserSettings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
async def get_settings(request: Request) -> UserSettings:
    return request.app.state.user_settings_store.get()


@router.put("", response_model=UserSettings)
async def put_settings(request: Request, body: UserSettings) -> UserSettings:
    return request.app.state.user_settings_store.update(body)
