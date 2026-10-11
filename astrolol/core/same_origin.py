"""Same-origin enforcement for the HTTP and WebSocket API.

astrolol has no authentication, so any web page the user visits could otherwise
drive the telescope through the browser. CORS alone is not enough: it only stops
a foreign page from *reading* responses — "simple" cross-origin requests (form
POSTs, text/plain bodies) are still executed, and WebSockets are not covered by
CORS at all. This middleware rejects any request whose ``Origin`` header names a
different origin than the one the request was addressed to, before it reaches a
route. No ``Access-Control-Allow-*`` headers are ever emitted, so browsers also
refuse cross-origin reads and preflighted requests.

Requests without an ``Origin`` header (curl, native/mobile clients, same-origin
GETs) are not browser cross-site requests and pass through.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger()


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None


class SameOriginMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str] | None = None) -> None:
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in (allowed_origins or []) if o.strip()}

    def _is_allowed(self, scope: Scope) -> bool:
        origin = _header(scope, b"origin")
        if origin is None:
            return True
        origin = origin.rstrip("/").lower()
        if origin in self.allowed:
            return True
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
        if scope["type"] not in ("http", "websocket") or self._is_allowed(scope):
            await self.app(scope, receive, send)
            return

        logger.warning(
            "security.cross_origin_rejected",
            origin=_header(scope, b"origin"),
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
