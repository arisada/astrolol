"""Switching the INDI server in Options: the next start stops the one a previous run left.

A managed server outlives astrolol (the next run reuses it), so after a switch to the other
kind, or to another port, the old one would hold the port or answer instead of the new one.
Needs indiserver and indigo_server.
"""
from __future__ import annotations

import os
import shutil

import pytest

from astrolol.config.settings import settings
from astrolol.devices.indi.plugin import IndiConnectionManager

pytestmark = [
    pytest.mark.skipif(shutil.which("indiserver") is None, reason="indiserver not installed"),
    pytest.mark.skipif(shutil.which("indigo_server") is None, reason="indigo_server not installed"),
]

_PORT = 17861


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):  # noqa: ANN001
    monkeypatch.setenv("HOME", str(tmp_path / "home"))   # indigo_server's ~/.indigo
    monkeypatch.setattr(settings, "indi_manage_server", True)
    monkeypatch.setattr(settings, "indi_port", _PORT)


async def _run(kind: str, run_dir, monkeypatch, port: int = _PORT) -> IndiConnectionManager:  # noqa: ANN001
    monkeypatch.setattr(settings, "indi_server_kind", kind)
    monkeypatch.setattr(settings, "indi_port", port)
    manager = IndiConnectionManager(run_dir=run_dir)
    await manager.ensure_started()
    await manager.client.disconnect()      # astrolol stops; the server stays
    return manager


@pytest.mark.parametrize("first, then", [("indi", "indigo"), ("indigo", "indi")])
async def test_switching_kind_stops_the_old_server(first, then, tmp_path, monkeypatch):  # noqa: ANN001
    run_dir = tmp_path / "run"
    old = await _run(first, run_dir, monkeypatch)
    old_pid = old._server._managed_pid
    assert old_pid and _alive(old_pid)

    new = await _run(then, run_dir, monkeypatch)
    try:
        assert not _alive(old_pid)
        assert new._server._managed_pid not in (None, old_pid)
        assert new.server_kind == then
    finally:
        await new.stop_server()


async def test_the_same_server_is_reused(tmp_path, monkeypatch):  # noqa: ANN001
    run_dir = tmp_path / "run"
    old = await _run("indigo", run_dir, monkeypatch)
    new = await _run("indigo", run_dir, monkeypatch)
    try:
        assert new._server._managed_pid == old._server._managed_pid
    finally:
        await new.stop_server()


@pytest.mark.parametrize("kind", ["indi", "indigo"])
async def test_another_port_starts_another_server(kind, tmp_path, monkeypatch):  # noqa: ANN001
    run_dir = tmp_path / "run"
    old = await _run(kind, run_dir, monkeypatch)
    old_pid = old._server._managed_pid

    new = await _run(kind, run_dir, monkeypatch, port=_PORT + 1)
    try:
        assert not _alive(old_pid)
        assert new._server._managed_pid != old_pid
        await new.client.connect()          # it answers on the new port
    finally:
        await new.client.disconnect()
        await new.stop_server()
