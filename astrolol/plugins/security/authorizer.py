"""The security plugin's implementation of core.auth.Authorizer."""
from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path

import structlog
from starlette.requests import HTTPConnection

from astrolol.core.auth import SESSION_COOKIE, AuthError, Level, LoginResult, Principal
from astrolol.plugins.security.models import SecuritySettings
from astrolol.plugins.security.passwords import DUMMY_HASH, verify_password
from astrolol.plugins.security.store import SESSION_TTL, TOKEN_PREFIX, SecurityStore

logger = structlog.get_logger()

GUEST = Principal(name="guest", level=Level.VIEWER, kind="guest")

_WINDOW = 300.0
_MAX_PER_USER = 5
_MAX_PER_HOST = 30
_LOOPBACK = {"127.0.0.1", "::1"}


def load_service_token(path: Path) -> str:
    """Read astrolol's own helper-process credential, creating it on first use (mode 0600)."""
    try:
        token = path.read_text().strip()
        if token:
            return token
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    return token


class LoginThrottle:
    """Failed-login limiter: per user name and per client host, over a sliding window."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, key: str) -> deque[float]:
        q = self._fails[key]
        cutoff = self._clock() - _WINDOW
        while q and q[0] < cutoff:
            q.popleft()
        if not q:
            self._fails.pop(key, None)
            return deque()
        return q

    def check(self, user: str, host: str) -> None:
        for key, limit in ((f"u:{user.lower()}", _MAX_PER_USER), (f"h:{host}", _MAX_PER_HOST)):
            q = self._recent(key)
            if len(q) >= limit:
                raise AuthError("Too many failed logins, try again later", status=429,
                                retry_after=max(1, int(q[0] + _WINDOW - self._clock())))

    def failed(self, user: str, host: str) -> None:
        now = self._clock()
        self._fails[f"u:{user.lower()}"].append(now)
        self._fails[f"h:{host}"].append(now)

    def succeeded(self, user: str) -> None:
        self._fails.pop(f"u:{user.lower()}", None)


class SecurityAuthorizer:
    def __init__(
        self,
        store: SecurityStore,
        get_settings: Callable[[], SecuritySettings],
        service_token: str | None = None,
    ) -> None:
        self.store = store
        self._settings = get_settings
        self._service_token = service_token
        self.throttle = LoginThrottle()

    def enforcing(self) -> bool:
        return self.store.has_users()

    def guest_allowed(self) -> bool:
        return self._settings().guest_enabled

    async def authenticate(self, conn: HTTPConnection) -> Principal | None:
        auth = conn.headers.get("authorization", "")
        if auth[:7].lower() == "bearer ":
            return self._bearer(conn, auth[7:].strip())  # bad credentials never fall back to guest

        cookie = conn.cookies.get(SESSION_COOKIE)
        if cookie:
            found = self.store.session_user(cookie)
            if found:
                name, rec = found
                return Principal(name=name, level=Level.parse(rec.level), kind="user")
        return GUEST if self.guest_allowed() else None

    def _bearer(self, conn: HTTPConnection, secret: str) -> Principal | None:
        if self._service_token and hmac.compare_digest(secret, self._service_token):
            # Only astrolol's own helper processes (same host, not via a proxy) use this.
            host = conn.client.host if conn.client else ""
            if host in _LOOPBACK and "x-forwarded-for" not in conn.headers:
                return Principal(name="service", level=Level.OPERATOR, kind="service")
            return None
        if secret.startswith(TOKEN_PREFIX):
            rec = self.store.token_for(secret)
            if rec:
                return Principal(name=rec.name, level=Level.parse(rec.level), kind="token")
        return None

    async def login(self, username: str, password: str, client: str) -> LoginResult:
        self.throttle.check(username, client)
        found = self.store.get_user(username)
        stored = found[1].password_hash if found else DUMMY_HASH
        ok = await asyncio.to_thread(verify_password, password, stored)
        if not (ok and found):
            self.throttle.failed(username, client)
            logger.warning("security.login_failed", user=username, client=client)
            raise AuthError("Wrong user name or password")
        self.throttle.succeeded(username)
        name, rec = found
        logger.info("security.login", user=name, client=client)
        return LoginResult(
            principal=Principal(name=name, level=Level.parse(rec.level), kind="user"),
            session_token=self.store.create_session(name),
            max_age=SESSION_TTL,
        )

    async def logout(self, session_token: str | None) -> None:
        if session_token:
            self.store.end_session(session_token)
