import pytest
from pydantic import ValidationError

from astrolol.config.user_settings import UserSettings, UserSettingsStore


def test_theme_defaults_to_current(tmp_path):
    assert UserSettingsStore(tmp_path / "settings.json").get().theme == "midnight"


def test_theme_persists(tmp_path):
    path = tmp_path / "settings.json"
    UserSettingsStore(path).update(UserSettings(theme="night"))
    assert UserSettingsStore(path).get().theme == "night"


def test_legacy_settings_file_without_theme(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"language": "fr"}')
    settings = UserSettingsStore(path).get()
    assert settings.theme == "midnight"
    assert settings.language == "fr"


@pytest.mark.parametrize("bad", ["", "Night Red", "../x", "a" * 33])
def test_theme_rejects_odd_ids(bad):
    with pytest.raises(ValidationError):
        UserSettings(theme=bad)
