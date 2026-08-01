from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from filesearch.domain.models import ProviderProfile
from filesearch.services import indexing
from filesearch.storage.database import Database
from conftest import FakeProvider

PROFILE = ProviderProfile("test", "Test", "https://example.invalid/v1", "next-model", "KEY")


def seed(tmp_path, name: str, text: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / "doc.txt").write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def fake_provider(monkeypatch):
    """Swap the HTTP provider rebuild_all constructs for a local fake."""
    created = []

    class Factory:
        def __init__(self, profile, key, cancel=None, vision_profile=None, vision_key=""):
            self.instance = FakeProvider(model=profile.model)
            created.append(self)

        @property
        def model(self):
            return self.instance.model

        def __getattr__(self, name):
            return getattr(self.instance, name)

    monkeypatch.setattr("filesearch.providers.openai_compatible.OpenAICompatibleProvider", Factory)
    return created


def test_rebuild_all_reindexes_every_root(tmp_path, fake_provider):
    first = seed(tmp_path, "a", "договор аренды")
    second = seed(tmp_path, "b", "акт приёмки")
    live = tmp_path / "index.sqlite3"

    progress = indexing.rebuild_all([first, second], live, PROFILE, "key", Event(), lambda p: None)

    assert progress.processed == 2
    db = Database(live)
    assert db.stats() == (2, 2)
    assert sorted(db.roots()) == sorted([first.resolve(), second.resolve()])
    assert db.index_metadata().model == "next-model"
    db.close()


def test_rebuild_all_replaces_a_model_mismatched_index(tmp_path, fake_provider):
    """The whole point of rebuilding: switch models without a manual wipe."""
    root = seed(tmp_path, "a", "договор аренды")
    live = tmp_path / "index.sqlite3"
    old = Database(live)
    indexing.sync(root, old, FakeProvider(model="old-model"), Event(), lambda p: None)
    assert old.index_metadata().model == "old-model"
    old.close()

    indexing.rebuild_all([root], live, PROFILE, "key", Event(), lambda p: None)

    db = Database(live)
    assert db.index_metadata().model == "next-model"
    assert db.stats() == (1, 1)
    db.close()


def test_rebuild_all_keeps_the_old_index_when_it_fails(tmp_path, fake_provider, monkeypatch):
    root = seed(tmp_path, "a", "договор аренды")
    live = tmp_path / "index.sqlite3"
    original = Database(live)
    indexing.sync(root, original, FakeProvider(model="old-model"), Event(), lambda p: None)
    original.close()

    def explode(*args, **kwargs):
        raise RuntimeError("провайдер недоступен")

    monkeypatch.setattr(indexing, "sync", explode)
    with pytest.raises(RuntimeError):
        indexing.rebuild_all([root], live, PROFILE, "key", Event(), lambda p: None)

    db = Database(live)
    assert db.index_metadata().model == "old-model"  # untouched
    assert db.stats() == (1, 1)
    db.close()


def test_rebuild_all_removes_its_staging_files(tmp_path, fake_provider):
    root = seed(tmp_path, "a", "договор аренды")
    live = tmp_path / "index.sqlite3"
    indexing.rebuild_all([root], live, PROFILE, "key", Event(), lambda p: None)
    assert not list(tmp_path.glob("index.rebuild-*"))


def test_rebuild_all_refuses_to_publish_an_empty_index(tmp_path, fake_provider):
    empty = tmp_path / "empty"
    empty.mkdir()
    live = tmp_path / "index.sqlite3"
    with pytest.raises(ValueError, match="прежний индекс сохранён"):
        indexing.rebuild_all([empty], live, PROFILE, "key", Event(), lambda p: None)


def test_rebuild_all_does_not_publish_a_partial_index(tmp_path, fake_provider, monkeypatch):
    root = seed(tmp_path, "a", "новый документ")
    live = tmp_path / "index.sqlite3"
    original = Database(live)
    indexing.sync(root, original, FakeProvider(model="old-model"), Event(), lambda p: None)
    original.close()

    real_sync = indexing.sync

    def partial(*args, **kwargs):
        progress = real_sync(*args, **kwargs)
        progress.failed += 1
        progress.errors.append("часть архива не обработана")
        return progress

    monkeypatch.setattr(indexing, "sync", partial)
    with pytest.raises(RuntimeError, match="прежний индекс сохранён"):
        indexing.rebuild_all([root], live, PROFILE, "key", Event(), lambda p: None)

    db = Database(live)
    assert db.index_metadata().model == "old-model"
    db.close()


def test_rebuild_all_honours_cancel_before_atomic_swap(tmp_path, fake_provider, monkeypatch):
    root = seed(tmp_path, "a", "новый документ")
    live = tmp_path / "index.sqlite3"
    original = Database(live)
    indexing.sync(root, original, FakeProvider(model="old-model"), Event(), lambda p: None)
    original.close()
    cancel = Event()
    real_sync = indexing.sync

    def cancel_after_sync(*args, **kwargs):
        progress = real_sync(*args, **kwargs)
        cancel.set()
        return progress

    monkeypatch.setattr(indexing, "sync", cancel_after_sync)
    with pytest.raises(InterruptedError):
        indexing.rebuild_all([root], live, PROFILE, "key", cancel, lambda p: None)

    db = Database(live)
    assert db.index_metadata().model == "old-model"
    db.close()


def test_rebuild_all_rechecks_cancel_after_staging_is_closed(tmp_path, fake_provider, monkeypatch):
    """Cancellation in the publication hand-off must not replace the live DB."""
    root = seed(tmp_path, "a", "новый документ")
    live = tmp_path / "index.sqlite3"
    original = Database(live)
    indexing.sync(root, original, FakeProvider(model="old-model"), Event(), lambda p: None)
    original.close()
    cancel = Event()
    real_close = Database.close
    closed_staging = False

    def cancel_when_staging_closes(self):
        nonlocal closed_staging
        if ".rebuild-" in self.path.name and not closed_staging:
            closed_staging = True
            real_close(self)
            cancel.set()
            return
        real_close(self)

    monkeypatch.setattr(Database, "close", cancel_when_staging_closes)

    with pytest.raises(InterruptedError):
        indexing.rebuild_all([root], live, PROFILE, "key", cancel, lambda p: None)

    db = Database(live)
    assert db.index_metadata().model == "old-model"
    db.close()
