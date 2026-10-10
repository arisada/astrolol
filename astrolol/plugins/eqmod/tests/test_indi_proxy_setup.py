"""Registering the INDI mount proxy with astrolol's indiserver."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from astrolol.plugins.eqmod.indi_proxy_setup import LAUNCHER_NAME, PROXY_SCRIPT, IndiProxyRegistration, write_launcher


class _FakeIndiManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._startup_drivers: list[str] = []
        self._started = False

    async def add_startup_driver(self, executable: str) -> None:
        self.calls.append(("add", executable))

    async def remove_startup_driver(self, executable: str) -> None:
        self.calls.append(("remove", executable))


def test_launcher_is_an_executable_named_after_the_proxy(tmp_path) -> None:
    path = write_launcher(tmp_path, "http://127.0.0.1:8123")
    assert path.name == LAUNCHER_NAME == "astrolol-indi-mount-proxy"
    assert os.access(path, os.X_OK)
    text = path.read_text()
    assert sys.executable in text and str(PROXY_SCRIPT) in text and "http://127.0.0.1:8123" in text
    assert "Not a real mount driver" in text


def test_launcher_runs_the_proxy(tmp_path) -> None:
    """The generated launcher really starts the proxy (it answers getProperties)."""
    path = write_launcher(tmp_path, "http://127.0.0.1:9")
    out = subprocess.run([str(path)], input=b'<getProperties version="1.7"/>', capture_output=True, timeout=10)
    assert b'name="DRIVER_INFO"' in out.stdout


@pytest.mark.asyncio
async def test_enable_registers_a_startup_driver(tmp_path) -> None:
    manager = _FakeIndiManager()
    reg = IndiProxyRegistration(manager, tmp_path)
    await reg.apply(True, "http://127.0.0.1:8000")
    assert manager.calls == [("add", str(tmp_path / LAUNCHER_NAME))]
    assert (tmp_path / LAUNCHER_NAME).exists()


@pytest.mark.asyncio
async def test_unchanged_settings_do_not_restart_the_proxy(tmp_path) -> None:
    manager = _FakeIndiManager()
    reg = IndiProxyRegistration(manager, tmp_path)
    await reg.apply(True, "http://127.0.0.1:8000")
    await reg.apply(True, "http://127.0.0.1:8000")
    assert len(manager.calls) == 1


@pytest.mark.asyncio
async def test_changing_the_url_reloads_the_proxy(tmp_path) -> None:
    manager = _FakeIndiManager()
    reg = IndiProxyRegistration(manager, tmp_path)
    await reg.apply(True, "http://127.0.0.1:8000")
    await reg.apply(True, "http://127.0.0.1:8123")
    launcher = str(tmp_path / LAUNCHER_NAME)
    assert manager.calls == [("add", launcher), ("remove", launcher), ("add", launcher)]
    assert "8123" in (tmp_path / LAUNCHER_NAME).read_text()


@pytest.mark.asyncio
async def test_disable_unregisters(tmp_path) -> None:
    manager = _FakeIndiManager()
    reg = IndiProxyRegistration(manager, tmp_path)
    await reg.apply(True, "http://127.0.0.1:8000")
    await reg.apply(False, "http://127.0.0.1:8000")
    assert manager.calls[-1] == ("remove", str(tmp_path / LAUNCHER_NAME))
    assert reg.status()["enabled"] is False


@pytest.mark.asyncio
async def test_disabled_from_the_start_touches_nothing(tmp_path) -> None:
    manager = _FakeIndiManager()
    await IndiProxyRegistration(manager, tmp_path).apply(False, "http://127.0.0.1:8000")
    assert manager.calls == []


@pytest.mark.asyncio
async def test_without_indi_support_it_is_a_noop(tmp_path) -> None:
    reg = IndiProxyRegistration(None, tmp_path)
    await reg.apply(True, "http://127.0.0.1:8000")
    assert reg.status()["indi_available"] is False
