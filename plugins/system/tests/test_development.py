"""Development tools: git pull (fast-forward only) and UI rebuild."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plugins.system import development
from plugins.system.models import CommandResult
from plugins.system.tests.test_system_api import _make_app


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
def repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    origin, clone = tmp_path / "origin", tmp_path / "clone"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    (origin / "a.txt").write_text("1")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "one")
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    monkeypatch.setattr(development, "REPO_ROOT", clone)
    return origin, clone


async def test_git_pull_fast_forwards(repos: tuple[Path, Path]) -> None:
    origin, clone = repos
    (origin / "b.txt").write_text("2")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "two")
    result = await development.git_pull()
    assert result.ok
    assert (clone / "b.txt").exists()


async def test_git_pull_refuses_diverged_history(repos: tuple[Path, Path]) -> None:
    origin, clone = repos
    (origin / "b.txt").write_text("2")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "remote")
    (clone / "c.txt").write_text("3")
    _git(clone, "add", ".")
    _git(clone, "commit", "-m", "local")
    result = await development.git_pull()
    assert not result.ok
    assert not (clone / "b.txt").exists()  # nothing merged


async def test_missing_command_is_reported(tmp_path: Path) -> None:
    result = await development._run(["definitely-not-a-command"], tmp_path, timeout=5)
    assert not result.ok
    assert "definitely-not-a-command" in result.output


async def test_timeout_is_reported(tmp_path: Path) -> None:
    result = await development._run(["sleep", "10"], tmp_path, timeout=0.1)
    assert not result.ok
    assert "Timed out" in result.output


async def test_rebuild_ui_runs_npm_build_in_ui_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], Path]] = []

    async def fake_run(cmd: list[str], cwd: Path, timeout: float) -> CommandResult:
        calls.append((cmd, cwd))
        return CommandResult(ok=True, output="built")

    monkeypatch.setattr(development, "_run", fake_run)
    assert (await development.rebuild_ui()).ok
    assert calls == [(["npm", "run", "build"], development.UI_DIR)]


def test_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_pull() -> CommandResult:
        return CommandResult(ok=True, output="Already up to date.")

    monkeypatch.setattr(development, "git_pull", fake_pull)
    client = TestClient(_make_app())
    r = client.post("/plugins/system/dev/git_pull")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "output": "Already up to date."}
