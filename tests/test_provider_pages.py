from __future__ import annotations

import os
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from filesearch.gui.pages.providers_page import ProvidersPage
from filesearch.gui.pages.vision_page import VisionPage
from filesearch.gui.pages.index_page import IndexPage
from filesearch.gui import main_window as main_window_module
from filesearch.storage.settings_store import SettingsStore


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def make_settings(tmp_path):
    return SettingsStore(tmp_path / "settings.json", tmp_path / ".env")


def test_embedding_test_refusal_does_not_start_a_worker(app, tmp_path):
    settings = make_settings(tmp_path)
    asked = []
    page = ProvidersPage(settings, lambda: None, lambda profile, vision=None: asked.append(profile) or False)

    page.test()

    assert len(asked) == 1
    assert page._test_thread is None
    assert "разрешена" in page.status.text().lower()


def test_embedding_test_consents_to_the_model_visible_in_the_form(app, tmp_path):
    settings = make_settings(tmp_path)
    profile = settings.load_profiles()[0]
    settings.save_provider_models(profile.id, [profile.model, "other/embed"], profile.model)
    asked = []
    page = ProvidersPage(settings, lambda: None, lambda candidate, vision=None: asked.append(candidate) or False)
    page.model.setCurrentText("other/embed")

    page.test()

    assert asked[0].model == "other/embed"
    assert settings.load_profiles()[0].model == profile.model  # refusal changes no settings


def test_vision_test_refusal_does_not_start_a_worker(app, tmp_path):
    settings = make_settings(tmp_path)
    asked = []
    page = VisionPage(settings, lambda: None, lambda profile: asked.append(profile) or False)

    page.test()

    assert len(asked) == 1
    assert page._test_thread is None
    assert "разрешена" in page.status.text().lower()


def test_vision_success_message_does_not_call_it_an_embedding_vector(app, tmp_path):
    page = VisionPage(make_settings(tmp_path), lambda: None, lambda profile: True)

    page.test_done(10)

    assert "vision" in page.status.text().lower()
    assert "вектор" not in page.status.text().lower()


def test_provider_page_permanently_discloses_remote_data_flow(app, tmp_path):
    page = ProvidersPage(make_settings(tmp_path), lambda: None)

    text = page.privacy_note.text().lower()
    assert "текст запроса" in text
    assert "одну" in text and "страниц" in text
    assert "визуаль" in text
    assert ".env" in text
    assert "https://routerai.ru/api/v1" in text


def test_selecting_an_index_replaces_roots_from_the_previous_index(app, tmp_path, monkeypatch):
    from filesearch.storage.database import Database

    settings = make_settings(tmp_path)
    old_root = tmp_path / "old"; old_root.mkdir()
    new_root = tmp_path / "new"; new_root.mkdir()
    settings.save_roots([old_root])
    imported_path = tmp_path / "imported.sqlite3"
    imported = Database(imported_path); imported.add_root(new_root); imported.close()
    monkeypatch.setattr(main_window_module, "SettingsStore", lambda: settings)
    window = main_window_module.MainWindow()

    window.select_index(str(imported_path))

    assert settings.load_roots() == [new_root.resolve()]
    window.database.close()
    window._allow_close = True
    window.close()


def test_index_page_disables_vision_profile_and_persists_choice(app, tmp_path):
    from filesearch.storage.database import Database

    settings = make_settings(tmp_path)
    db = Database(tmp_path / "index.sqlite3")
    calls = []

    class Provider:
        def close(self):
            pass

    def provider_factory(include_vision=True):
        calls.append(include_vision)
        return Provider()

    page = IndexPage(settings, db, provider_factory)
    assert page.vision_toggle.isChecked()

    page.vision_toggle.setChecked(False)
    profile, vision = page._active_profiles()

    assert profile is not None
    assert vision is None
    assert calls == [False]
    assert settings.vision_indexing_enabled() is False
    db.close()
