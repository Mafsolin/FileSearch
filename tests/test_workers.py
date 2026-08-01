from __future__ import annotations

from threading import Event

from filesearch.domain.models import ProviderProfile, SourceChunk, VisionProfile
from filesearch.gui import workers
from filesearch.storage.database import Database


def test_search_checks_index_model_before_remote_embedding(tmp_path, monkeypatch):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "a.txt"
    path.write_text("a", encoding="utf-8")
    db_path = tmp_path / "index.sqlite3"
    db = Database(db_path)
    db.add_root(root)
    db.replace(root, path, "digest", "txt", [SourceChunk("Текст", "договор", [1.0, 0.0])], "old-model")
    db.close()

    calls = []

    class Provider:
        model = "new-model"

        def __init__(self, *args, **kwargs):
            pass

        def embed_text(self, text):
            calls.append(text)
            return [1.0, 0.0]

        def close(self):
            pass

    monkeypatch.setattr(workers, "OpenAICompatibleProvider", Provider)
    profile = ProviderProfile("p", "Provider", "https://example.invalid/v1", "new-model", "KEY")
    worker = workers.SearchWorker("запрос", 5, profile, "key", db_path, Event())
    errors = []
    worker.failed.connect(errors.append)

    worker.run()

    assert errors
    assert not calls


def test_vision_test_worker_sends_one_small_image(monkeypatch):
    calls = []

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe_image(self, payload, filename):
            calls.append((payload, filename))
            return "FileSearch"

        def close(self):
            pass

    monkeypatch.setattr(workers, "OpenAICompatibleProvider", Provider)
    profile = VisionProfile("v", "Vision", "https://example.invalid/v1", "vision", "KEY")
    worker = workers.VisionTestWorker(profile, "key", Event())
    results = []
    worker.finished.connect(results.append)

    worker.run()

    assert results == [len("FileSearch")]
    assert len(calls) == 1
    assert calls[0][0].startswith(b"\x89PNG")
