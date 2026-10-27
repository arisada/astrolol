from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, HTTPException, Request, Response

from astrolol.core.auth import Level, principal_of, set_session_cookie
from astrolol.plugins.security.authorizer import SecurityAuthorizer
from astrolol.plugins.security.models import (
    PasswordChange,
    SecuritySettings,
    TokenCreate,
    TokenCreated,
    TokenOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from astrolol.plugins.security.passwords import hash_password, verify_password
from astrolol.plugins.security.store import SESSION_TTL, TokenRecord, UserRecord, now

logger = structlog.get_logger()

router = APIRouter(prefix="/plugins/security", tags=["security"])


def _authz(request: Request) -> SecurityAuthorizer:
    return request.app.state.security


def _token_out(rec: TokenRecord) -> dict:
    return dict(id=rec.id, name=rec.name, level=rec.level, hint=rec.hint,
                created=rec.created, expires=rec.expires, last_used=rec.last_used)


@router.get("/settings", response_model=SecuritySettings)
async def get_settings(request: Request) -> SecuritySettings:
    return request.app.state.plugin_ctx.get_plugin_settings("security", SecuritySettings)


@router.put("/settings", response_model=SecuritySettings)
async def put_settings(body: SecuritySettings, request: Request) -> SecuritySettings:
    request.app.state.plugin_ctx.save_plugin_settings("security", body)
    logger.info("security.settings_changed", guest=body.guest_enabled, origins=body.allowed_origins)
    return body


# ── users ────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(request: Request) -> list[UserOut]:
    return [UserOut(name=n, level=r.level, created=r.created) for n, r in _authz(request).store.users()]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, request: Request, response: Response) -> UserOut:
    store = _authz(request).store
    if store.get_user(body.name):
        raise HTTPException(status_code=409, detail="That user already exists")
    first = not store.has_users()
    # The very first account takes over the API, so it must be able to manage the rest.
    level = "admin" if first else body.level
    hashed = await asyncio.to_thread(hash_password, body.password)
    rec = UserRecord(password_hash=hashed, level=level, created=now().isoformat())
    store.put_user(body.name, rec)
    logger.info("security.user_created", user=body.name, level=level, first=first)
    if first:
        # Authentication is on from now on: keep the person who just set it up logged in.
        set_session_cookie(response, request, store.create_session(body.name), SESSION_TTL)
    return UserOut(name=body.name, level=level, created=rec.created)


@router.put("/users/{name}", response_model=UserOut)
async def update_user(name: str, body: UserUpdate, request: Request) -> UserOut:
    store = _authz(request).store
    found = store.get_user(name)
    if found is None:
        raise HTTPException(status_code=404, detail="No such user")
    display, rec = found
    update: dict = {}
    if body.level is not None:
        if rec.level == "admin" and body.level != "admin" and store.admin_count() <= 1:
            raise HTTPException(status_code=409, detail="There must be at least one admin")
        update["level"] = body.level
    if body.password is not None:
        update["password_hash"] = await asyncio.to_thread(hash_password, body.password)
    rec = rec.model_copy(update=update)
    store.put_user(display, rec)
    if body.password is not None:
        store.drop_sessions(display)  # a reset password logs the user out everywhere
    logger.info("security.user_updated", user=display, level=rec.level, password_reset=body.password is not None)
    return UserOut(name=display, level=rec.level, created=rec.created)


@router.delete("/users/{name}", status_code=204, response_model=None)
async def delete_user(name: str, request: Request) -> None:
    store = _authz(request).store
    found = store.get_user(name)
    if found is None:
        raise HTTPException(status_code=404, detail="No such user")
    if found[1].level == "admin" and store.admin_count() <= 1:
        raise HTTPException(status_code=409, detail="There must be at least one admin")
    store.delete_user(name)
    logger.info("security.user_deleted", user=found[0])


@router.post("/me/password", status_code=204, response_model=None)
async def change_own_password(body: PasswordChange, request: Request) -> None:
    principal = principal_of(request)
    if principal is None or principal.kind != "user":
        raise HTTPException(status_code=403, detail="Only signed-in users have a password")
    store = _authz(request).store
    found = store.get_user(principal.name)
    if found is None or not await asyncio.to_thread(verify_password, body.current_password, found[1].password_hash):
        raise HTTPException(status_code=403, detail="Current password is wrong")
    hashed = await asyncio.to_thread(hash_password, body.new_password)
    store.put_user(found[0], found[1].model_copy(update={"password_hash": hashed}))
    store.drop_sessions(found[0])
    logger.info("security.password_changed", user=found[0])


# ── API tokens ───────────────────────────────────────────────────────────────

@router.get("/tokens", response_model=list[TokenOut])
async def list_tokens(request: Request) -> list[dict]:
    return [_token_out(t) for t in _authz(request).store.tokens()]


@router.post("/tokens", response_model=TokenCreated, status_code=201)
async def create_token(body: TokenCreate, request: Request) -> dict:
    secret, rec = _authz(request).store.create_token(body.name, body.level, body.expires_in_days)
    logger.info("security.token_created", token=rec.name, level=rec.level)
    return {**_token_out(rec), "token": secret}


@router.delete("/tokens/{token_id}", status_code=204, response_model=None)
async def delete_token(token_id: str, request: Request) -> None:
    if not _authz(request).store.delete_token(token_id):
        raise HTTPException(status_code=404, detail="No such token")
    logger.info("security.token_revoked", id=token_id)
