"""Calls astrolol's own REST API in-process, as the caller of the MCP request.

Every tool goes through here instead of reaching into the managers: the request
passes the same middleware (origin check, sign-in, access level) as any REST call, with
the caller's own credentials. A viewer's token therefore cannot slew, whatever the
tool says.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI

# Credentials forwarded from the MCP request to the REST call.
_FORWARDED = ("authorization", "cookie")

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:@+-]+$")


class ToolError(Exception):
    """A failure the model should read and act on (shown as an error result, not a crash)."""


@dataclass
class ApiResponse:
    status: int
    data: Any  # parsed JSON, or None for an empty body
    body: bytes
    content_type: str


def safe_id(value: Any, what: str = "device_id") -> str:
    """A device/job/task id fit for a URL path segment (no separators, no traversal)."""
    if not isinstance(value, str) or not _SAFE_ID.match(value) or value in {".", ".."}:
        raise ToolError(f"Invalid {what}: {value!r}")
    return value


def _detail(resp: ApiResponse) -> str:
    data = resp.data
    if isinstance(data, dict) and "detail" in data:
        detail = data["detail"]
        if isinstance(detail, list):  # pydantic validation errors
            return "; ".join(
                f"{'.'.join(str(p) for p in e.get('loc', []) if p != 'body')}: {e.get('msg')}"
                for e in detail if isinstance(e, dict)
            )
        return detail if isinstance(detail, str) else json.dumps(detail)
    return resp.body[:300].decode("utf-8", "replace")


class ApiClient:
    def __init__(self, app: FastAPI, headers: dict[str, str]) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://astrolol",
            headers={k: v for k, v in headers.items() if k.lower() in _FORWARDED},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        timeout: float = 60.0,
        ok_missing: bool = False,
    ) -> ApiResponse:
        """Perform the request; raise ToolError on any status >= 400 (404 allowed with ok_missing)."""
        query = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            async with asyncio.timeout(timeout):
                r = await self._client.request(method, path, params=query, json=json_body)
        except TimeoutError:
            raise ToolError(f"{method} {path} did not finish within {timeout:.0f} s") from None
        ctype = r.headers.get("content-type", "")
        data: Any = None
        if r.content and "json" in ctype:
            try:
                data = r.json()
            except ValueError:
                data = None
        resp = ApiResponse(r.status_code, data, r.content, ctype)
        if resp.status == 404 and ok_missing:
            return resp
        if resp.status >= 400:
            raise ToolError(f"{method} {path} failed with {resp.status}: {_detail(resp)}")
        return resp

    async def get(self, path: str, **kw: Any) -> Any:
        return (await self.call("GET", path, **kw)).data

    async def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return (await self.call("POST", path, json_body=body, **kw)).data

    async def put(self, path: str, body: Any = None, **kw: Any) -> Any:
        return (await self.call("PUT", path, json_body=body, **kw)).data

    async def delete(self, path: str, **kw: Any) -> Any:
        return (await self.call("DELETE", path, **kw)).data
