"""The INDI server chosen in Options: saved in the user settings, used from the next start.

The start-up configuration (ASTROLOL_INDI_*, or the configuration file) wins over the choice.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.config import settings as settings_mod
from astrolol.config.settings import INDI_SERVER_FIELDS, apply_indi_server_choice, settings
from astrolol.config.user_settings import IndiServerChoice, UserSettings


@pytest.fixture(autouse=True)
def _restore_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Applying a choice changes the global settings: put them back after each test.
    for field in INDI_SERVER_FIELDS.values():
        monkeypatch.setattr(settings, field, getattr(settings, field))
    monkeypatch.setattr(settings, "profiles_file", tmp_path / "profiles.json")
    monkeypatch.setattr(settings_mod, "CONFIGURED_FIELDS", frozenset())


def test_choice_is_applied() -> None:
    apply_indi_server_choice(IndiServerChoice(kind="indigo", managed=False, host="astro.local", port=7625))
    assert (settings.indi_server_kind, settings.indi_manage_server) == ("indigo", False)
    assert (settings.indi_host, settings.indi_port) == ("astro.local", 7625)


def test_unset_parts_keep_the_default() -> None:
    port = settings.indi_port
    apply_indi_server_choice(IndiServerChoice(kind="indigo"))
    assert (settings.indi_server_kind, settings.indi_port) == ("indigo", port)


def test_environment_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod, "CONFIGURED_FIELDS", frozenset({"indi_port"}))
    monkeypatch.setattr(settings, "indi_port", 7700)
    apply_indi_server_choice(IndiServerChoice(kind="indigo", port=7625))
    assert (settings.indi_server_kind, settings.indi_port) == ("indigo", 7700)
    assert settings_mod.indi_server_configured_keys() == ["port"]


def test_old_settings_files_load() -> None:
    assert UserSettings.model_validate({"language": "fr"}).indi_server == IndiServerChoice()


@pytest.mark.parametrize("bad", [{"port": 0}, {"port": 70000}, {"host": ""}, {"host": "a b"},
                                 {"kind": "ascom"}, {"indigo_path": ""}])
def test_bad_choices_are_refused(bad: dict) -> None:
    with pytest.raises(ValueError):
        IndiServerChoice(**bad)


async def _get_server(app) -> dict:  # noqa: ANN001
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/indi/server")
    assert r.status_code == 200
    return r.json()


async def test_saved_choice_needs_a_restart() -> None:
    from astrolol.main import create_app

    settings.indi_server_kind = "indi"
    settings.indi_manage_server = True
    app = create_app()
    info = await _get_server(app)
    assert info["next"]["kind"] == "indi" and info["restart_needed"] is False

    store = app.state.profile_store
    store.update_user_settings(store.get_user_settings().model_copy(
        update={"indi_server": IndiServerChoice(kind="indigo", managed=True, indigo_path="/opt/indigo_server")},
    ))
    info = await _get_server(app)
    assert info["kind"] == "indi"                      # still running indiserver
    assert info["next"]["kind"] == "indigo"
    assert info["next"]["indigo_path"] == "/opt/indigo_server"
    assert info["restart_needed"] is True

    # The next start uses it.
    info = await _get_server(create_app())
    assert info["kind"] == "indigo" and info["restart_needed"] is False


async def test_parts_that_do_not_matter_need_no_restart() -> None:
    from astrolol.main import create_app

    settings.indi_server_kind = "indi"
    settings.indi_manage_server = True
    app = create_app()
    store = app.state.profile_store
    # The INDIGO program with indiserver, the host with a server astrolol starts.
    store.update_user_settings(store.get_user_settings().model_copy(
        update={"indi_server": IndiServerChoice(kind="indi", managed=True, host="elsewhere", indigo_path="/x")},
    ))
    assert (await _get_server(app))["restart_needed"] is False


async def test_environment_fixed_parts_are_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    from astrolol.main import create_app

    monkeypatch.setattr(settings_mod, "CONFIGURED_FIELDS", frozenset({"indi_server_kind"}))
    settings.indi_server_kind = "indi"
    app = create_app()
    store = app.state.profile_store
    store.update_user_settings(store.get_user_settings().model_copy(
        update={"indi_server": IndiServerChoice(kind="indigo")},
    ))
    info = await _get_server(app)
    assert info["env"] == ["kind"]
    assert info["next"]["kind"] == "indi" and info["restart_needed"] is False
