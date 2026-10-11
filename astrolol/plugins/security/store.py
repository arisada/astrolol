"""Persistence for users, API tokens and sessions: one JSON file, mode 0600, hashed secrets."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

from astrolol.plugins.security.models import LevelName

logger = structlog.get_logger()

SESSION_TTL = 30 * 24 * 3600
TOKEN_PREFIX = "astl_"
_LAST_USED_FLUSH = 60.0  # seconds between writes caused by token use


def now() -> datetime:
    return datetime.now(timezone.utc)


def sha256(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


class UserRecord(BaseModel):
    password_hash: str
    level: LevelName
    created: str


class TokenRecord(BaseModel):
    id: str
    name: str
    hash: str
    hint: str
    level: LevelName
    created: str
    expires: str | None = None
    last_used: str | None = None


class SessionRecord(BaseModel):
    user: str
    created: str
    expires: str


class SecurityData(BaseModel):
    users: dict[str, UserRecord] = Field(default_factory=dict)      # key: lower-case name
    names: dict[str, str] = Field(default_factory=dict)             # lower-case -> display name
    tokens: list[TokenRecord] = Field(default_factory=list)
    sessions: dict[str, SessionRecord] = Field(default_factory=dict)  # key: sha256(session id)


class SecurityStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data = self._load()
        self._last_flush = 0.0

    def _load(self) -> SecurityData:
        if self._path.exists():
            try:
                return SecurityData.model_validate_json(self._path.read_text())
            except Exception as exc:
                # Don't silently start with an empty (= open) user list.
                logger.error("security.store_unreadable", path=str(self._path), error=str(exc))
                raise
        return SecurityData()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(self._data.model_dump_json(indent=2))
        os.replace(tmp, self._path)
        self._last_flush = time.monotonic()

    # ── users ──
    def has_users(self) -> bool:
        return bool(self._data.users)

    def users(self) -> list[tuple[str, UserRecord]]:
        return [(self._data.names[k], v) for k, v in sorted(self._data.users.items())]

    def get_user(self, name: str) -> tuple[str, UserRecord] | None:
        key = name.lower()
        rec = self._data.users.get(key)
        return (self._data.names[key], rec) if rec else None

    def put_user(self, name: str, record: UserRecord) -> None:
        key = name.lower()
        self._data.users[key] = record
        self._data.names[key] = name
        self._save()

    def delete_user(self, name: str) -> None:
        key = name.lower()
        self._data.users.pop(key, None)
        self._data.names.pop(key, None)
        self._data.sessions = {h: s for h, s in self._data.sessions.items() if s.user != key}
        self._save()

    def admin_count(self) -> int:
        return sum(1 for u in self._data.users.values() if u.level == "admin")

    def drop_sessions(self, user: str) -> None:
        key = user.lower()
        self._data.sessions = {h: s for h, s in self._data.sessions.items() if s.user != key}
        self._save()

    # ── sessions ──
    def create_session(self, user: str) -> str:
        token = new_secret()
        created = now()
        self._data.sessions[sha256(token)] = SessionRecord(
            user=user.lower(), created=created.isoformat(),
            expires=(created + timedelta(seconds=SESSION_TTL)).isoformat(),
        )
        self._prune_sessions()
        self._save()
        return token

    def session_user(self, token: str) -> tuple[str, UserRecord] | None:
        rec = self._data.sessions.get(sha256(token))
        if rec is None:
            return None
        if datetime.fromisoformat(rec.expires) <= now():
            self._data.sessions.pop(sha256(token), None)
            self._save()
            return None
        return self.get_user(rec.user)

    def end_session(self, token: str) -> None:
        if self._data.sessions.pop(sha256(token), None) is not None:
            self._save()

    def _prune_sessions(self) -> None:
        t = now()
        self._data.sessions = {
            h: s for h, s in self._data.sessions.items() if datetime.fromisoformat(s.expires) > t
        }

    # ── tokens ──
    def tokens(self) -> list[TokenRecord]:
        return list(self._data.tokens)

    def create_token(self, name: str, level: LevelName, expires_in_days: int | None) -> tuple[str, TokenRecord]:
        secret = TOKEN_PREFIX + new_secret()
        created = now()
        rec = TokenRecord(
            id=secrets.token_hex(4), name=name, hash=sha256(secret), hint=secret[: len(TOKEN_PREFIX) + 4],
            level=level, created=created.isoformat(),
            expires=(created + timedelta(days=expires_in_days)).isoformat() if expires_in_days else None,
        )
        self._data.tokens.append(rec)
        self._save()
        return secret, rec

    def delete_token(self, token_id: str) -> bool:
        before = len(self._data.tokens)
        self._data.tokens = [t for t in self._data.tokens if t.id != token_id]
        if len(self._data.tokens) == before:
            return False
        self._save()
        return True

    def token_for(self, secret: str) -> TokenRecord | None:
        digest = sha256(secret)
        for rec in self._data.tokens:
            if rec.hash == digest:
                if rec.expires and datetime.fromisoformat(rec.expires) <= now():
                    return None
                rec.last_used = now().isoformat()
                if time.monotonic() - self._last_flush > _LAST_USED_FLUSH:
                    self._save()
                return rec
        return None
