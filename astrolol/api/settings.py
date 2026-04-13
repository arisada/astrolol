from fastapi import APIRouter, Request

from astrolol.config.user_settings import UserSettings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
async def get_settings(request: Request) -> UserSettings:
    return request.app.state.profile_store.get_user_settings()


@router.put("", response_model=UserSettings)
async def put_settings(request: Request, body: UserSettings) -> UserSettings:
    return request.app.state.profile_store.update_user_settings(body)
