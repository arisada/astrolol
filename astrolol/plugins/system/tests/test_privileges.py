"""polkit permissions: what pkcheck says, and how to install the rule from a checkout."""
from __future__ import annotations

import pwd
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrolol.plugins.system import privileges


async def test_check_reports_each_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = {privileges.ACTIONS["network"], privileges.ACTIONS["timezone"]}

    async def fake(action_id: str) -> bool:
        return action_id in allowed

    monkeypatch.setattr(privileges, "_authorized", fake)
    assert await privileges.check() == {
        "network": True, "reboot": False, "shutdown": False, "hostname": False, "timezone": True,
    }


async def test_without_pkcheck_nothing_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    assert await privileges._authorized(privileges.ACTIONS["reboot"]) is False


def test_every_checked_action_is_in_the_rule() -> None:
    rule = privileges.RULES_FILE.read_text()
    for action in privileges.ACTIONS.values():
        assert action in rule or action.startswith("org.freedesktop.NetworkManager."), action
    assert '"org.freedesktop.NetworkManager."' in rule


def _as_user(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name=name))


def test_setup_for_the_astrolol_user_copies_the_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    _as_user(monkeypatch, "astrolol")
    [cmd] = privileges.setup_commands()
    assert cmd.startswith("sudo install -m 644 ") and cmd.endswith("/etc/polkit-1/rules.d/50-astrolol.rules")


def test_setup_for_another_user_names_that_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _as_user(monkeypatch, "pi")
    [cmd] = privileges.setup_commands()
    assert "\"pi\"" in cmd and str(privileges.RULES_FILE) in cmd


def test_no_setup_without_the_rule_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A packaged install: the rule ships with the package, there is nothing to copy.
    monkeypatch.setattr(privileges, "RULES_FILE", tmp_path / "50-astrolol.rules")
    assert privileges.setup_commands() == []
