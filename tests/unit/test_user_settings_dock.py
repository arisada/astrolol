import pytest
from pydantic import ValidationError

from astrolol.config.user_settings import DockSettings, DockWidget, UserSettings, UserSettingsStore


def test_dock_is_empty_by_default(tmp_path):
    assert UserSettingsStore(tmp_path / "settings.json").get().dock.widgets == []


def test_dock_layout_persists_in_order(tmp_path):
    path = tmp_path / "settings.json"
    dock = DockSettings(widgets=[DockWidget(id="guider.target"), DockWidget(id="mount.position", collapsed=True)])
    UserSettingsStore(path).update(UserSettings(dock=dock))
    widgets = UserSettingsStore(path).get().dock.widgets
    assert [w.id for w in widgets] == ["guider.target", "mount.position"]
    assert [w.collapsed for w in widgets] == [False, True]


def test_legacy_settings_file_without_dock(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"language": "fr"}')
    assert UserSettingsStore(path).get().dock.widgets == []


@pytest.mark.parametrize("bad", ["", "nodot", "Guider.Target", "../x.y", "a.b.c"])
def test_dock_rejects_odd_widget_ids(bad):
    with pytest.raises(ValidationError):
        DockWidget(id=bad)


def test_dock_is_bounded():
    with pytest.raises(ValidationError):
        DockSettings(widgets=[DockWidget(id=f"a.w{i}") for i in range(51)])
