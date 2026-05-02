"""Tests for GET /admin/log_scopes and POST /admin/log_level."""
import logging

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from astrolol.core.plugin_api import LogScope


# ── Minimal test app that mirrors the real endpoint logic ─────────────────────

def make_app(scopes: list[LogScope]) -> FastAPI:
    app = FastAPI()
    app.state.log_scopes = scopes

    @app.get("/admin/log_scopes")
    def get_scopes(request: Request) -> list[dict]:
        result = []
        for scope in request.app.state.log_scopes:
            effective = logging.getLogger(scope.logger).getEffectiveLevel()
            result.append({
                "key": scope.key,
                "label": scope.label,
                "logger": scope.logger,
                "level": "debug" if effective <= logging.DEBUG else "info",
            })
        return result

    class _LogLevelRequest(BaseModel):
        key: str
        level: str

    @app.post("/admin/log_level", status_code=204)
    def set_level(body: _LogLevelRequest, request: Request) -> None:
        scopes_list: list[LogScope] = request.app.state.log_scopes
        scope = next((s for s in scopes_list if s.key == body.key), None)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"Unknown log scope: {body.key!r}")
        new_level = logging.DEBUG if body.level == "debug" else logging.INFO
        logging.getLogger(scope.logger).setLevel(new_level)

    return app


@pytest.fixture()
def scopes() -> list[LogScope]:
    return [
        LogScope(key="mount",  label="Mount",        logger="test.log.mount"),
        LogScope(key="imager", label="Imaging",       logger="test.log.imager"),
        LogScope(key="phd2",   label="PHD2 Guiding",  logger="test.log.phd2"),
    ]


@pytest.fixture(autouse=True)
def reset_loggers(scopes):
    """Restore logger levels to NOTSET after each test to avoid cross-test pollution."""
    yield
    for scope in scopes:
        logging.getLogger(scope.logger).setLevel(logging.NOTSET)


@pytest.fixture()
def client(scopes) -> TestClient:
    return TestClient(make_app(scopes))


# ── GET /admin/log_scopes ─────────────────────────────────────────────────────

def test_log_scopes_returns_all(client):
    r = client.get("/admin/log_scopes")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    keys = {s["key"] for s in data}
    assert keys == {"mount", "imager", "phd2"}


def test_log_scopes_default_level_is_info(client):
    r = client.get("/admin/log_scopes")
    for scope in r.json():
        assert scope["level"] == "info"


def test_log_scopes_reflects_debug_level(scopes, client):
    logging.getLogger("test.log.mount").setLevel(logging.DEBUG)
    r = client.get("/admin/log_scopes")
    levels = {s["key"]: s["level"] for s in r.json()}
    assert levels["mount"] == "debug"
    assert levels["imager"] == "info"


def test_log_scopes_includes_label_and_logger(client):
    r = client.get("/admin/log_scopes")
    mount = next(s for s in r.json() if s["key"] == "mount")
    assert mount["label"] == "Mount"
    assert mount["logger"] == "test.log.mount"


# ── POST /admin/log_level ─────────────────────────────────────────────────────

def test_set_debug_changes_logger_level(client):
    r = client.post("/admin/log_level", json={"key": "phd2", "level": "debug"})
    assert r.status_code == 204
    assert logging.getLogger("test.log.phd2").level == logging.DEBUG


def test_set_info_restores_logger_level(client):
    logging.getLogger("test.log.phd2").setLevel(logging.DEBUG)
    client.post("/admin/log_level", json={"key": "phd2", "level": "info"})
    assert logging.getLogger("test.log.phd2").level == logging.INFO


def test_set_level_unknown_key_returns_404(client):
    r = client.post("/admin/log_level", json={"key": "nonexistent", "level": "debug"})
    assert r.status_code == 404


def test_set_level_reflected_in_scopes_endpoint(client):
    client.post("/admin/log_level", json={"key": "imager", "level": "debug"})
    r = client.get("/admin/log_scopes")
    levels = {s["key"]: s["level"] for s in r.json()}
    assert levels["imager"] == "debug"
    assert levels["phd2"] == "info"
