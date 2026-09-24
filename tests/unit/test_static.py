"""Tests for the SPA fallback in astrolol.api.static.

An unmatched request under a known backend API prefix (e.g. a disabled
plugin's "/plugins/<id>/..." routes) must 404, not silently fall back to the
SPA shell with a 200 — otherwise callers can't tell "not found" from "here's
your page" (fetch().ok is true for HTML just as much as for JSON).
"""
from __future__ import annotations

from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.api import static


@pytest.fixture()
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>spa shell</body></html>")

    app = FastAPI()
    # spa_fallback reads the module-level UI_DIST at request time, so the patch
    # must stay active for the lifetime of the TestClient, not just during mount.
    with patch.object(static, "UI_DIST", dist):
        static.mount_ui(app)
        yield TestClient(app)


def test_disabled_plugin_route_returns_404(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search?q=M31")
    assert resp.status_code == 404


@pytest.mark.parametrize("prefix", sorted(static._API_PREFIXES))
def test_unmatched_known_api_prefixes_return_404(client: TestClient, prefix: str) -> None:
    resp = client.get(f"/{prefix}/does-not-exist")
    assert resp.status_code == 404


def test_prefix_match_is_exact_not_substring(client: TestClient) -> None:
    # "pluginsomething" merely starts with "plugin" — must not be treated as
    # the "plugins" API prefix and must still fall back to the SPA shell.
    resp = client.get("/pluginsomething/page")
    assert resp.status_code == 200
    assert "spa shell" in resp.text


def test_client_route_falls_back_to_spa_shell(client: TestClient) -> None:
    resp = client.get("/equipment")
    assert resp.status_code == 200
    assert "spa shell" in resp.text


def test_root_falls_back_to_spa_shell(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "spa shell" in resp.text
