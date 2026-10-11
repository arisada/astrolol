"""Same-origin enforcement for the HTTP and WebSocket API.

astrolol's API can be driven by any web page the user visits unless the browser is
told otherwise. CORS alone is not enough: it only stops a foreign page from *reading*
responses — "simple" cross-origin requests (form POSTs, text/plain bodies) are still
executed, and WebSockets are not covered by CORS at all. This middleware rejects any
request whose ``Origin`` header names a different origin than the one the request was
addressed to, before it reaches a route.

Origins listed as allowed (``ASTROLOL_ALLOWED_ORIGINS`` and the security plugin's
setting) are the exception: they pass, and get CORS headers so a web app on another
host can call the API with a bearer token. Credentials (cookies) are never allowed
cross-origin.

Requests without an ``Origin`` header (curl, native/mobile clients, same-origin
GETs) are not browser cross-site requests and pass through.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger()

# A provider returns the currently allowed extra origins; evaluated per request so
# changes made in the UI apply without a restart.
OriginProvider = Callable[[], Iterable[str]]


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None


def _norm(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


class SameOriginMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: Iterable[str] | None = None,
        providers: list[OriginProvider] | None = None,
    ) -> None:
        self.app = app
        self._static = {_norm(o) for o in (allowed_origins or []) if o.strip()}
        # Shared list: plugins append providers after the middleware is built.
        self.providers = providers if providers is not None else []

    def _extra(self) -> set[str]:
        out = set(self._static)
        for provider in self.providers:
            try:
                out.update(_norm(o) for o in provider() if o.strip())
            except Exception:  # a broken provider must not open or break the API
                logger.warning("security.origin_provider_failed", exc_info=True)
        return out

    def _same_origin(self, scope: Scope, origin: str) -> bool:
        # "null" (sandboxed iframes, file://) and unparsable origins never match.
        netloc = urlsplit(origin).netloc
        if not netloc:
            return False
        hosts = {h.strip().lower() for h in (_header(scope, b"host") or "").split(",")}
        forwarded = _header(scope, b"x-forwarded-host")
        if forwarded:
            hosts.add(forwarded.split(",")[0].strip().lower())
        return netloc in hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        raw = _header(scope, b"origin")
        if raw is None:
            await self.app(scope, receive, send)
            return
        origin = _norm(raw)
        if self._same_origin(scope, origin):
            await self.app(scope, receive, send)
            return

        if origin in self._extra():
            await self._allowed_cross_origin(scope, receive, send, raw)
            return

        logger.warning(
            "security.cross_origin_rejected",
            origin=raw,
            host=_header(scope, b"host"),
            path=scope.get("path"),
        )
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008})
            return
        body = b'{"detail":"Cross-origin request rejected"}'
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})

    async def _allowed_cross_origin(self, scope: Scope, receive: Receive, send: Send, origin: str) -> None:
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        cors = [(b"access-control-allow-origin", origin.encode("latin-1")), (b"vary", b"Origin")]
        if scope["method"] == "OPTIONS" and _header(scope, b"access-control-request-method"):
            await send({"type": "http.response.start", "status": 204, "headers": cors + [
                (b"access-control-allow-methods", b"GET, POST, PUT, DELETE, PATCH, OPTIONS"),
                (b"access-control-allow-headers", b"Authorization, Content-Type"),
                (b"access-control-max-age", b"600"),
                (b"content-length", b"0"),
            ]})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *cors]}
            await send(message)

        await self.app(scope, receive, send_with_cors)
