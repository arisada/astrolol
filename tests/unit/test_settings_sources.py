"""Where the start-up configuration comes from: code defaults < configuration file < environment."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from astrolol.api import static
from astrolol.config import settings as settings_mod
from astrolol.config.settings import Settings


@pytest.fixture()
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A configuration file Settings reads, and no data directory in the environment."""
    path = tmp_path / "astrolol.toml"
    monkeypatch.setitem(Settings.model_config, "toml_file", path)
    monkeypatch.delenv("ASTROLOL_DATA_DIR", raising=False)
    return path


def test_without_a_file_everything_is_a_default(config_file: Path) -> None:
    s = Settings()
    assert s.data_dir == Path.home() / ".astrolol"
    assert s.model_fields_set == set()


def test_paths_follow_the_data_dir_of_the_file(config_file: Path, tmp_path: Path) -> None:
    config_file.write_text(f'data_dir = "{tmp_path / "data"}"\n')
    s = Settings()
    assert s.data_dir == tmp_path / "data"
    assert s.profiles_file == tmp_path / "data" / "profiles.json"
    assert s.security_file == tmp_path / "data" / "security.json"
    # Images too: no longer relative to wherever astrolol was started.
    assert s.images_dir == tmp_path / "data" / "images"


def test_a_file_can_still_move_one_path(config_file: Path, tmp_path: Path) -> None:
    config_file.write_text(f'data_dir = "{tmp_path / "data"}"\nimages_dir = "{tmp_path / "usb"}"\n')
    s = Settings()
    assert s.images_dir == tmp_path / "usb"
    assert s.log_file == tmp_path / "data" / "astrolol.log"


def test_the_environment_wins_over_the_file(
    config_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file.write_text(f'data_dir = "{tmp_path / "data"}"\nindi_port = 7700\n')
    monkeypatch.setenv("ASTROLOL_INDI_PORT", "7800")
    monkeypatch.setenv("ASTROLOL_DATA_DIR", str(tmp_path / "other"))
    s = Settings()
    assert s.indi_port == 7800
    assert s.profiles_file == tmp_path / "other" / "profiles.json"


def test_what_the_file_sets_counts_as_configured(config_file: Path) -> None:
    # Fields set by the file are greyed out in Options, like those set in the environment.
    config_file.write_text('indi_server_kind = "indigo"\n')
    assert Settings().model_fields_set == {"indi_server_kind"}


def test_a_typo_in_the_file_stops_the_start(config_file: Path) -> None:
    config_file.write_text("indi_prot = 7700\n")
    with pytest.raises(ValidationError, match="indi_prot"):
        Settings()


def test_ui_dist_setting_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(settings_mod.settings, "ui_dist", dist)
    assert static._find_ui_dist() == dist


def test_ui_dist_setting_that_does_not_exist_serves_no_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_mod.settings, "ui_dist", tmp_path / "missing")
    assert static._find_ui_dist() is None


def test_the_packaged_ui_comes_before_the_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # An installed astrolol (wheel or .deb) carries its UI as astrolol/_ui.
    packaged = tmp_path / "_ui"
    packaged.mkdir()
    (packaged / "index.html").write_text("<html></html>")
    monkeypatch.setattr(settings_mod.settings, "ui_dist", None)
    monkeypatch.setattr(static, "PACKAGED_UI", packaged)
    assert static._find_ui_dist() == packaged


def test_an_empty_packaged_ui_directory_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod.settings, "ui_dist", None)
    monkeypatch.setattr(static, "PACKAGED_UI", tmp_path / "_ui")
    assert static._find_ui_dist() != tmp_path / "_ui"
