"""Authentication and authorisation seam.

Core owns the enforcement point; a plugin (``astrolol/plugins/security``) supplies
the identities. With no ``app.state.authorizer`` — or an authorizer that reports
``enforcing() == False`` — every request passes, which is the default.

Three ordered access levels:

* ``viewer``   — read-only: observe status, images, logs.
* ``operator`` — operate the telescope and run tasks.
* ``admin``    — change configuration: settings, plugins, hardware, users.

A request needs the level given by the first matching ACL rule, or ``viewer`` for
GET/HEAD and ``operator`` for anything else when no rule matches. Unannotated
mutating routes are therefore never open to viewers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol, runtime_checkable

import structlog
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger()

SESSION_COOKIE = "astrolol_session"


class Level(IntEnum):
    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3

    @classmethod
    def parse(cls, name: str) -> "Level":
        return cls[name.upper()]

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Principal:
    name: str
    level: Level
    kind: str  # "user" | "guest" | "token" | "service"


class AuthError(Exception):
    """Login refused. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 401, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass
class LoginResult:
    principal: Principal
    session_token: str
    max_age: int


@runtime_checkable
class Authorizer(Protocol):
    def enforcing(self) -> bool:
        """True once credentials are required (e.g. at least one user exists)."""
        ...

    def guest_allowed(self) -> bool: ...

    async def authenticate(self, conn: HTTPConnection) -> Principal | None:
        """Resolve the caller, or None when no valid credentials were presented."""
        ...

    async def login(self, username: str, password: str, client: str) -> LoginResult: ...

    async def logout(self, session_token: str | None) -> None: ...


# ── ACL ──────────────────────────────────────────────────────────────────────

_READ_METHODS = ("GET", "HEAD")


@dataclass
class AclRule:
    """Access rule. ``path`` supports ``*`` (one segment) and ``**`` (any depth).

    ``methods=None`` matches every method. ``level=None`` makes the path public
    (reachable without credentials).
    """
    path: str
    level: Level | None
    methods: tuple[str, ...] | None = None


def _compile(pattern: str) -> re.Pattern[str]:
    # "/x/**" also covers "/x" itself.
    if pattern.endswith("/**"):
        return re.compile(_compile(pattern[:-3]).pattern.removesuffix("/?$") + "(?:/.*)?$")
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]+")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "/?$")


class Acl:
    """Ordered rules; the first match wins. Plugin rules are checked before core defaults."""

    def __init__(self) -> None:
        self._defaults: list[tuple[AclRule, re.Pattern[str]]] = []
        self._plugin: list[tuple[AclRule, re.Pattern[str]]] = []

    def add_default(self, *rules: AclRule) -> None:
        self._defaults.extend((r, _compile(r.path)) for r in rules)

    def add_plugin(self, *rules: AclRule) -> None:
        self._plugin.extend((r, _compile(r.path)) for r in rules)

    def lookup(self, method: str, path: str) -> tuple[bool, Level]:
        """Return ``(public, level)`` for a request."""
        method = method.upper()
        for rules in (self._plugin, self._defaults):
            for rule, rx in rules:
                if (rule.methods is None or method in rule.methods) and rx.match(path):
                    if rule.level is None:
                        return True, Level.VIEWER
                    return False, rule.level
        return False, (Level.VIEWER if method in _READ_METHODS or method == "OPTIONS" else Level.OPERATOR)


_W = ("POST", "PUT", "DELETE", "PATCH")


def default_acl() -> Acl:
    acl = Acl()
    acl.add_default(
        AclRule("/health", None),
        AclRule("/auth/**", None),
        AclRule("/admin/**", Level.ADMIN),
        AclRule("/settings", Level.ADMIN, _W),
        AclRule("/inventory/**", Level.ADMIN, _W),
        # Operators run the night: switch the active profile off/on, but not edit profiles.
        AclRule("/profiles/active", Level.OPERATOR, ("DELETE",)),
        AclRule("/profiles/*/activate", Level.OPERATOR, ("POST",)),
        AclRule("/profiles/**", Level.ADMIN, _W),
        # A connect request carries adapter parameters (INDI driver executable, serial paths).
        AclRule("/devices/connect", Level.ADMIN, ("POST",)),
        AclRule("/devices/connected/*", Level.ADMIN, ("DELETE",)),
        AclRule("/devices/bluetooth/**", Level.ADMIN, _W),
        AclRule("/indi/load_driver", Level.ADMIN, _W),
        AclRule("/indi/debug", Level.ADMIN, _W),
    )
    return acl


# ── Middleware ───────────────────────────────────────────────────────────────

def _api_prefixes() -> frozenset[str]:
    from astrolol.api.static import _API_PREFIXES
    return _API_PREFIXES


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state["principal"] = None
        fastapi_app = scope.get("app")
        authz: Authorizer | None = getattr(getattr(fastapi_app, "state", None), "authorizer", None)
        if authz is None or not authz.enforcing():
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        first = path.lstrip("/").split("/", 1)[0]
        principal = await authz.authenticate(HTTPConnection(scope))
        state["principal"] = principal
        # The UI shell (static files and client-side routes) must load to show the login form.
        if first not in _api_prefixes():
            await self.app(scope, receive, send)
            return

        acl: Acl = fastapi_app.state.acl
        method = "GET" if scope["type"] == "websocket" else scope["method"]
        public, needed = acl.lookup(method, path)
        if public:
            await self.app(scope, receive, send)
            return
        if principal is None:
            await self._reject(scope, receive, send, 401, "Authentication required")
            return
        if principal.level < needed:
            logger.warning("security.forbidden", user=principal.name, level=principal.level.label,
                           needed=needed.label, method=method, path=path)
            await self._reject(scope, receive, send, 403,
                               f"Requires {needed.label} access (you are {principal.level.label})")
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 4000 + status})
            return
        import json
        body = json.dumps({"detail": detail}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


def principal_of(request) -> Principal | None:  # noqa: ANN001
    """The authenticated caller of *request*, or None when the API is open."""
    return getattr(request.state, "principal", None)


def is_https(request) -> bool:  # noqa: ANN001
    """True when the browser reached us over TLS (directly, or via a proxy that says so)."""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return (forwarded or request.url.scheme) == "https"


def set_session_cookie(response, request, token: str, max_age: int) -> None:  # noqa: ANN001
    # SameSite=Strict + the origin check keep other sites from riding the session.
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, path="/", httponly=True,
        samesite="strict", secure=is_https(request),
    )
