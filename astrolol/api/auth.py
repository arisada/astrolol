"""Who am I, log in, log out. Delegates to whatever authorizer the security plugin installed."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from astrolol.core.auth import SESSION_COOKIE, AuthError, is_https, principal_of, set_session_cookie

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/status")
async def auth_status(request: Request) -> dict:
    """Who the caller is, and whether the API asks for credentials at all."""
    authz = request.app.state.authorizer
    secure = is_https(request)
    if authz is None or not authz.enforcing():
        return {"enforced": False, "authenticated": True, "name": None, "level": "admin",
                "kind": None, "guest_allowed": False, "secure_transport": secure}
    principal = principal_of(request)
    return {
        "enforced": True,
        "authenticated": principal is not None,
        "name": principal.name if principal else None,
        "level": principal.level.label if principal else None,
        "kind": principal.kind if principal else None,
        "guest_allowed": authz.guest_allowed(),
        "secure_transport": secure,
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> dict:
    authz = request.app.state.authorizer
    if authz is None or not authz.enforcing():
        raise HTTPException(status_code=409, detail="Authentication is not enabled")
    client = request.client.host if request.client else ""
    try:
        result = await authz.login(body.username, body.password, client)
    except AuthError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=exc.status, detail=str(exc), headers=headers) from exc
    set_session_cookie(response, request, result.session_token, result.max_age)
    return {"name": result.principal.name, "level": result.principal.level.label}


@router.post("/logout", status_code=204, response_model=None)
async def logout(request: Request, response: Response) -> None:
    authz = request.app.state.authorizer
    if authz is not None:
        await authz.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
