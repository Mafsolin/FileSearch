import json
from PySide6.QtGui import QColor

from filesearch.gui import theme
from filesearch.storage.settings_store import SettingsStore


def test_visual_preferences_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path=path, secrets_path=tmp_path / ".env")

    assert store.theme() == theme.LIGHT
    assert store.animations_enabled() is True

    store.set_theme(theme.DARK)
    store.set_animations_enabled(False)

    reloaded = SettingsStore(path=path, secrets_path=tmp_path / ".env")
    assert reloaded.theme() == theme.DARK
    assert reloaded.animations_enabled() is False


def test_unknown_theme_falls_back_to_light(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "sepia"}), encoding="utf-8")

    store = SettingsStore(path=path, secrets_path=tmp_path / ".env")

    assert store.theme() == theme.LIGHT


def test_both_themes_generate_complete_stylesheets():
    for name in (theme.LIGHT, theme.DARK):
        colors = theme.palette(name)
        qss = theme.stylesheet(name)

        assert "#navRail" in qss
        assert "QProgressBar::chunk" in qss
        assert colors.canvas in qss
        assert colors.accent in qss
        assert colors.text in qss


def test_elevation_colors_are_valid_qt_colors():
    for name in (theme.LIGHT, theme.DARK):
        colors = theme.palette(name)
        assert QColor(colors.shadow_soft).isValid()
        assert QColor(colors.shadow_key).isValid()
