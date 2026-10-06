from astrolol.config.user_settings import UserSettings, UserSettingsStore


def test_language_defaults_to_english(tmp_path):
    assert UserSettingsStore(tmp_path / "settings.json").get().language == "en"


def test_language_persists(tmp_path):
    path = tmp_path / "settings.json"
    store = UserSettingsStore(path)
    store.update(UserSettings(language="fr"))
    assert UserSettingsStore(path).get().language == "fr"


def test_legacy_settings_file_without_language(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"low_memory_mode": true}')
    settings = UserSettingsStore(path).get()
    assert settings.language == "en"
    assert settings.low_memory_mode is True
