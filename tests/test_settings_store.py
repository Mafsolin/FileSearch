from __future__ import annotations

import json

from filesearch.domain.models import ProviderProfile, VisionProfile
from filesearch.storage.settings_store import SettingsStore

PROFILE = ProviderProfile("p1", "Provider", "https://example.invalid/v1", "embed-1", "FS_TEST_KEY")
VISION = VisionProfile("v1", "Vision", "https://vision.invalid/v1", "see-1", "FS_TEST_KEY")
OTHER_VISION = VisionProfile("v2", "Other", "https://elsewhere.invalid/v1", "see-1", "FS_TEST_KEY")


def store(tmp_path) -> SettingsStore:
    return SettingsStore(path=tmp_path / "settings.json", secrets_path=tmp_path / ".env")


def test_consent_covers_the_vision_endpoint(tmp_path):
    """Scans go to the vision host, so its identity must be consented to."""
    settings = store(tmp_path)
    settings.grant_consent(PROFILE, VISION)

    assert settings.has_consent(PROFILE, VISION)
    assert not settings.has_consent(PROFILE, OTHER_VISION)
    assert not settings.has_consent(PROFILE, None)


def test_consent_is_revoked_by_changing_the_vision_model(tmp_path):
    settings = store(tmp_path)
    settings.grant_consent(PROFILE, VISION)
    changed = VisionProfile(VISION.id, VISION.name, VISION.base_url, "see-2", VISION.key_name)
    assert not settings.has_consent(PROFILE, changed)


def test_consent_is_revoked_by_changing_the_embedding_model(tmp_path):
    settings = store(tmp_path)
    settings.grant_consent(PROFILE, VISION)
    changed = ProviderProfile(PROFILE.id, PROFILE.name, PROFILE.base_url, "embed-2", PROFILE.key_name)
    assert not settings.has_consent(changed, VISION)


def test_saved_key_wins_over_the_environment(tmp_path, monkeypatch):
    """A stale shell variable must not shadow the key entered in the UI."""
    settings = store(tmp_path)
    monkeypatch.setenv("FS_TEST_KEY", "from-environment")
    settings.set_key(PROFILE, "from-ui")
    assert settings.get_key(PROFILE) == "from-ui"


def test_environment_is_used_when_nothing_is_saved(tmp_path, monkeypatch):
    settings = store(tmp_path)
    monkeypatch.setenv("FS_TEST_KEY", "from-environment")
    assert settings.get_key(PROFILE) == "from-environment"


def test_deleting_a_key_falls_back_to_the_environment(tmp_path, monkeypatch):
    settings = store(tmp_path)
    settings.set_key(PROFILE, "from-ui")
    settings.delete_key(PROFILE)
    monkeypatch.setenv("FS_TEST_KEY", "from-environment")
    assert settings.get_key(PROFILE) == "from-environment"


def test_nested_roots_are_rejected(tmp_path):
    settings = store(tmp_path)
    parent = tmp_path / "archive"
    child = parent / "2024"
    child.mkdir(parents=True)
    try:
        settings.save_roots([parent, child])
    except ValueError as error:
        assert "вложенные" in str(error)
    else:
        raise AssertionError("nested roots should be rejected")


def test_corrupt_settings_file_is_quarantined(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")
    settings = SettingsStore(path=path, secrets_path=tmp_path / ".env")
    assert settings.theme() == "light"  # defaults, no crash
    assert list(tmp_path.glob("settings.json.corrupt-*"))


def test_non_object_settings_file_is_quarantined(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[]", encoding="utf-8")
    settings = SettingsStore(path=path, secrets_path=tmp_path / ".env")

    assert settings.theme() == "light"
    assert list(tmp_path.glob("settings.json.corrupt-*"))


def test_quarantine_exposes_a_clear_warning(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("broken", encoding="utf-8")

    settings = SettingsStore(path=path, secrets_path=tmp_path / ".env")
    settings.theme()

    assert settings.warning is not None
    assert "повреждён" in settings.warning.lower()
    assert ".corrupt-" in settings.warning
    assert settings.pop_warning() is not None
    assert settings.pop_warning() is None


def test_env_round_trips_special_characters_atomically(tmp_path):
    settings = store(tmp_path)
    secret = 'line one\nline "two" # value ${HOME}'

    settings.set_key(PROFILE, secret)

    assert settings.get_key(PROFILE) == secret
    assert not (tmp_path / ".env.tmp").exists()


def test_invalid_provider_records_are_skipped_with_a_diagnostic(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {"id": "", "name": "Broken", "base_url": "https://example.com/v1", "model": "m", "key_name": "KEY"},
                    {"id": "ok", "name": "Custom", "base_url": "https://example.com/v1", "model": "m", "key_name": "KEY", "builtin": True},
                    {"id": "ok", "name": "Duplicate", "base_url": "https://example.org/v1", "model": "m2", "key_name": "KEY2"},
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = SettingsStore(path=path, secrets_path=tmp_path / ".env")

    profiles = settings.load_profiles()

    assert [profile.id for profile in profiles] == ["routerai", "ok"]
    assert profiles[1].builtin is False  # persisted JSON cannot impersonate a preset
    assert settings.warning and "профил" in settings.warning.lower()


def test_malformed_model_catalogs_fall_back_without_crashing(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "provider_models": [],
                "provider_active_models": [],
                "vision_provider_models": "broken",
                "vision_active_models": 42,
            }
        ),
        encoding="utf-8",
    )
    settings = SettingsStore(path=path, secrets_path=tmp_path / ".env")

    assert settings.load_profiles()[0].model == "google/gemini-embedding-2"
    assert settings.load_vision_profiles()[0].model == "qwen/qwen3.7-flash"
    assert settings.warning is not None


def test_vision_indexing_is_enabled_by_default(tmp_path):
    assert store(tmp_path).vision_indexing_enabled() is True


def test_vision_indexing_choice_round_trips(tmp_path):
    settings = store(tmp_path)
    settings.set_vision_indexing_enabled(False)

    reloaded = store(tmp_path)

    assert reloaded.vision_indexing_enabled() is False
