from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

LevelName = Literal["viewer", "operator", "admin"]

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
MIN_PASSWORD = 8


class SecuritySettings(BaseModel):
    """Non-secret configuration, persisted under UserSettings.plugin_settings["security"]."""
    guest_enabled: bool = False
    allowed_origins: list[str] = []

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            o = raw.strip().rstrip("/")
            if not o:
                continue
            if not re.match(r"^https?://[^/\s]+$", o, re.IGNORECASE):
                raise ValueError(f"not an origin (expected scheme://host[:port]): {raw}")
            if o not in out:
                out.append(o)
        return out


class UserOut(BaseModel):
    name: str
    level: LevelName
    created: str


class UserCreate(BaseModel):
    name: str
    password: str = Field(min_length=MIN_PASSWORD)
    level: LevelName = "operator"

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError("user names are 1-32 letters, digits, '.', '_' or '-'")
        return v


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=MIN_PASSWORD)
    level: LevelName | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    level: LevelName = "operator"
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class TokenOut(BaseModel):
    id: str
    name: str
    level: LevelName
    hint: str          # first characters of the token, to recognise it in a list
    created: str
    expires: str | None
    last_used: str | None


class TokenCreated(TokenOut):
    token: str         # shown once, never stored in clear
