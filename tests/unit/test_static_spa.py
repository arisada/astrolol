"""Reloading a client page whose path is also a REST endpoint must show the UI, not JSON."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.api import static

NAVIGATE = {"Sec-Fetch-Dest": "document", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
FETCH = {"Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Accept": "*/*"}


@pytest.fixture()
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa shell</html>")
    app = FastAPI()

    @app.get("/profiles")
    async def profiles() -> list[str]:
        return ["api"]

    @app.get("/mount/status")
    async def mount_status() -> dict[str, str]:
        return {"api": "status"}

    with patch.object(static, "UI_DIST", dist):
        static.mount_ui(app)
        yield TestClient(app)


@pytest.mark.parametrize("path", ["/profiles", "/profiles/", "/mount"])
def test_navigation_gets_the_app_shell(client: TestClient, path: str) -> None:
    resp = client.get(path, headers=NAVIGATE)
    assert resp.status_code == 200
    assert "spa shell" in resp.text


def test_navigation_passed_on_by_the_service_worker_gets_the_shell(client: TestClient) -> None:
    # Chrome: the service worker's fetch(event.request) of a reload.
    resp = client.get("/profiles", headers={**NAVIGATE, "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "navigate"})
    assert "spa shell" in resp.text


def test_navigation_without_fetch_metadata_uses_accept(client: TestClient) -> None:
    resp = client.get("/profiles", headers={"Accept": "text/html,*/*"})
    assert "spa shell" in resp.text


@pytest.mark.parametrize("headers", [FETCH, {"Accept": "application/json"}, {}])
def test_fetch_still_reaches_the_api(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get("/profiles", headers=headers).json() == ["api"]


def test_api_subpaths_stay_api_for_navigations(client: TestClient) -> None:
    assert client.get("/mount/status", headers=NAVIGATE).json() == {"api": "status"}


def test_the_shell_and_the_api_are_never_cached_for_each_other(client: TestClient) -> None:
    # The browser cached the shell from a reload and gave it to fetch("/profiles").
    shell = client.get("/profiles", headers=NAVIGATE)
    assert shell.headers["cache-control"] == "no-store"
    assert shell.headers["vary"] == "Sec-Fetch-Mode, Sec-Fetch-Dest, Accept"
    assert client.get("/profiles", headers=FETCH).headers["vary"] == "Sec-Fetch-Mode, Sec-Fetch-Dest, Accept"


def test_only_get_is_a_navigation(client: TestClient) -> None:
    assert client.post("/profiles", headers=NAVIGATE).text != "<html>spa shell</html>"


def test_every_client_route_shadowing_an_api_prefix_is_handled() -> None:
    """Adding a UI page at a path an API prefix already owns must be declared in static.py."""
    app_tsx = (Path(__file__).resolve().parents[2] / "ui" / "src" / "App.tsx").read_text()
    first_segments = {m.split("/")[0] for m in re.findall(r'<Route path="/([^"]+)"', app_tsx)}
    assert first_segments & static._API_PREFIXES <= static._CLIENT_ROUTES_SHADOWING_API
